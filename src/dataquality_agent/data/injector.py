"""异常注入器：把干净数仓注入异常，输出 ground-truth（评估的地基）。"""
import random

import duckdb
from pydantic import BaseModel, Field

from dataquality_agent.config import Settings

# ground-truth 的「预期根因类别」→ 与 Diagnosis.root_cause_category 枚举对齐（归因正确率评估的地基）。
# 口径：注入器模拟的是真实根因造成的「结果」，不是「我们注入了脏数据」这个动作本身，所以能映射回业务语义。
ROOT_CAUSE_CATEGORY = {
    "duplicate": "脏数据注入",       # 重复行进入数仓
    "orphan": "上游任务失败",         # 上游订单被删/未加载 → 上游数据缺失
    "null_rate": "脏数据注入",        # 关键列被置空
    "value_range": "脏数据注入",      # 负价格等非法值
    "lineage_break": "上游数据延迟",  # 下游停更 → 上游数据未及时到达
    "freshness": "上游数据延迟",      # 数据停更/迟到
    "schema_drift": "schema变更",     # 列被删/改类型
}


class InjectedAnomaly(BaseModel):
    """单条注入记录 = ground-truth 的最小单元。root_cause_category 是「预期归因类别」，供评估对齐。"""

    type: str
    table: str
    column: str | None = None
    root_cause: str              # 真实根因（自由文本，供人类阅读 + LLM-as-a-Judge 对比）
    root_cause_category: str     # 预期根因类别（结构化，与 Diagnosis 枚举对齐，归因正确率的比较键）
    location: str


class GroundTruth(BaseModel):
    """一次注入的完整 ground-truth。"""

    injections: list[InjectedAnomaly] = Field(default_factory=list)


class Injector:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._rng = random.Random(settings.seed)

    def connect(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(self.settings.db_path)
        return self._conn

    def inject_duplicate(self, conn, table: str, key_cols: list[str], n: int = 1) -> InjectedAnomaly:
        """复制前 n 行，制造主键/唯一键重复。"""
        conn.execute(f"INSERT INTO {table} SELECT * FROM {table} LIMIT {n}")
        return InjectedAnomaly(
            type="duplicate",
            table=table,
            column=",".join(key_cols),
            root_cause="duplicate rows injected (data entry error)",
            root_cause_category=ROOT_CAUSE_CATEGORY["duplicate"],
            location=f"{n} rows duplicated in {table}",
        )

    def inject_orphan(self, conn, child_table: str, parent_table: str,
                      parent_pk: str, child_fk: str, n: int = 1) -> InjectedAnomaly:
        """删除父表前 n 行，制造子表外键悬空（孤儿记录）。"""
        pks = conn.execute(f"SELECT {parent_pk} FROM {parent_table} LIMIT {n}").fetchall()
        for (pk,) in pks:
            conn.execute(f"DELETE FROM {parent_table} WHERE {parent_pk} = ?", [pk])
        return InjectedAnomaly(
            type="orphan",
            table=child_table,
            column=child_fk,
            root_cause=f"upstream {parent_table} rows deleted",
            root_cause_category=ROOT_CAUSE_CATEGORY["orphan"],
            location=f"{len(pks)} rows deleted from {parent_table}",
        )

    def inject_null_rate(self, conn, table: str, column: str, status_col: str,
                         status_value: str, key_cols: list[str], n: int = 1) -> InjectedAnomaly:
        """把某 status 组内前 n 行 column 置 NULL，拉高该组 null 率（对应 L0 空值分层检测）。"""
        keys = conn.execute(
            f"SELECT {', '.join(key_cols)} FROM {table} "
            f"WHERE {status_col} = '{status_value}' AND {column} IS NOT NULL LIMIT {n}"
        ).fetchall()
        for key in keys:
            where = " AND ".join(f"{c} = ?" for c in key_cols)
            conn.execute(f"UPDATE {table} SET {column} = NULL WHERE {where}", list(key))
        return InjectedAnomaly(
            type="null_rate",
            table=table,
            column=column,
            root_cause=f"{column} nulled for {status_value} {table} (data entry error)",
            root_cause_category=ROOT_CAUSE_CATEGORY["null_rate"],
            location=f"{len(keys)} rows nulled in {table}.{column}",
        )

    def inject_value_range(self, conn, table: str, column: str, key_cols: list[str],
                           n: int = 1, bad_value: float = -5.0) -> InjectedAnomaly:
        """把前 n 行 column 改成非法值（如负价），制造值域异常。"""
        keys = conn.execute(f"SELECT {', '.join(key_cols)} FROM {table} LIMIT {n}").fetchall()
        for key in keys:
            where = " AND ".join(f"{c} = ?" for c in key_cols)
            conn.execute(f"UPDATE {table} SET {column} = ? WHERE {where}", [bad_value, *key])
        return InjectedAnomaly(
            type="value_range",
            table=table,
            column=column,
            root_cause=f"{column} set to {bad_value} (data entry error)",
            root_cause_category=ROOT_CAUSE_CATEGORY["value_range"],
            location=f"{len(keys)} rows corrupted in {table}.{column}",
        )

    def inject_lineage_break(self, conn, table: str, date_col: str, n: int = 1) -> InjectedAnomaly:
        """删除下游表最近 n 天，让下游水位线落后上游，制造血缘断裂。"""
        conn.execute(
            f"DELETE FROM {table} WHERE {date_col} IN "
            f"(SELECT {date_col} FROM {table} ORDER BY {date_col} DESC LIMIT {n})"
        )
        return InjectedAnomaly(
            type="lineage_break",
            table=table,
            column=date_col,
            root_cause=f"{table} 下游停更（最近 {n} 天未更新）",
            root_cause_category=ROOT_CAUSE_CATEGORY["lineage_break"],
            location=f"recent {n} days deleted from {table}",
        )

    def inject_freshness(self, conn, table: str, date_col: str, n: int = 1) -> InjectedAnomaly:
        """删除表最近 n 天，制造数据停更（freshness：最新分区日落后当前日期）。"""
        conn.execute(
            f"DELETE FROM {table} WHERE {date_col} IN "
            f"(SELECT {date_col} FROM {table} ORDER BY {date_col} DESC LIMIT {n})"
        )
        return InjectedAnomaly(
            type="freshness",
            table=table,
            column=date_col,
            root_cause=f"{table} 数据停更（最近 {n} 天缺失）",
            root_cause_category=ROOT_CAUSE_CATEGORY["freshness"],
            location=f"recent {n} days deleted from {table}",
        )

    def inject_schema(self, conn, table: str, drop_column: str) -> InjectedAnomaly:
        """删掉表的一列，制造 schema 漂移。"""
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {drop_column}")
        return InjectedAnomaly(
            type="schema_drift",
            table=table,
            column=drop_column,
            root_cause=f"{table} 缺失列 {drop_column}（schema 变更）",
            root_cause_category=ROOT_CAUSE_CATEGORY["schema_drift"],
            location=f"column {drop_column} dropped from {table}",
        )

    def run(self, conn, specs: list[dict]) -> GroundTruth:
        """按 specs 执行一组注入，返回完整 ground-truth。"""
        gt = GroundTruth()
        for spec in specs:
            t = spec["type"]
            if t == "duplicate":
                gt.injections.append(
                    self.inject_duplicate(conn, spec["table"], spec["key_cols"], spec.get("n", 1))
                )
            elif t == "orphan":
                gt.injections.append(
                    self.inject_orphan(
                        conn, spec["child_table"], spec["parent_table"],
                        spec["parent_pk"], spec["child_fk"], spec.get("n", 1),
                    )
                )
            elif t == "null_rate":
                gt.injections.append(
                    self.inject_null_rate(
                        conn, spec["table"], spec["column"], spec["status_col"],
                        spec["status_value"], spec["key_cols"], spec.get("n", 1),
                    )
                )
            elif t == "value_range":
                gt.injections.append(
                    self.inject_value_range(
                        conn, spec["table"], spec["column"], spec["key_cols"],
                        spec.get("n", 1), spec.get("bad_value", -5.0),
                    )
                )
            elif t == "lineage_break":
                gt.injections.append(
                    self.inject_lineage_break(conn, spec["table"], spec["date_col"], spec.get("n", 1))
                )
            elif t == "freshness":
                gt.injections.append(
                    self.inject_freshness(conn, spec["table"], spec["date_col"], spec.get("n", 1))
                )
            elif t == "schema_drift":
                gt.injections.append(
                    self.inject_schema(conn, spec["table"], spec["drop_column"])
                )
            else:
                raise ValueError(f"unknown injection type: {t}")
        return gt

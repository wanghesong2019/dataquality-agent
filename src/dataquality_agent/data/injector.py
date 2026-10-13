"""异常注入器：把干净数仓注入异常，输出 ground-truth（评估的地基）。"""
import random

import duckdb
from pydantic import BaseModel, Field

from dataquality_agent.config import Settings


class InjectedAnomaly(BaseModel):
    """单条注入记录 = ground-truth 的最小单元。root_cause 是"真实根因"，供评估对比。"""

    type: str
    table: str
    column: str | None = None
    root_cause: str
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
            location=f"{len(pks)} rows deleted from {parent_table}",
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
            else:
                raise ValueError(f"unknown injection type: {t}")
        return gt

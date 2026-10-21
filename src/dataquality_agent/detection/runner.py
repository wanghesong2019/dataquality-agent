"""检测调度：统一跑 L0/L1/L2 三层，产出 DetectionReport。"""
import time
from dataclasses import dataclass, field

import duckdb

from dataquality_agent.data.lineage import Lineage
from dataquality_agent.detection import rules, stats
from dataquality_agent.detection.semantic import run_semantic_checks
from dataquality_agent.models import Anomaly


@dataclass
class DetectionReport:
    """一次巡检的结果：异常清单 + 各检查耗时（秒）。"""

    anomalies: list[Anomaly] = field(default_factory=list)
    stats: dict[str, float] = field(default_factory=dict)


def _watermarks(conn) -> dict[str, str]:
    """每表更新水位线（最新数据日期），供血缘断裂检测。"""
    wm: dict[str, str] = {}
    row = conn.execute("SELECT MAX(order_purchase_timestamp::DATE) FROM dwd_orders").fetchone()
    if row[0] is not None:
        wm["orders"] = str(row[0])
    row = conn.execute("SELECT MAX(order_date) FROM daily_metrics").fetchone()
    if row[0] is not None:
        wm["daily_metrics"] = str(row[0])
    return wm


def run_detection(conn: duckdb.DuckDBPyConnection,
                  current_date: str | None = None,
                  expected_schema: dict | None = None,
                  zscore_threshold: float = 3.0,
                  psi_threshold: float = 0.10,
                  semantic_model=None) -> DetectionReport:
    """跑全部检测（dataset 级 → column 级），返回报告 + 各检查耗时。

    - current_date：freshness 的参照日期（ISO 字符串）；缺省 = 数据全局最新水位线（干净数据不误报）。
    - expected_schema：schema 漂移的期望快照 {table: {col: type}}；缺省跳过 schema 检测
      （需要从干净数仓捕获，eval harness 会传入）。
    - zscore_threshold / psi_threshold：volume 的 z-score 阈值 / distribution 的 PSI 阈值。
    - semantic_model：L2 语义检测用的 LLM（需有 .chat）；缺省跳过 L2（eval 干净数据不跑）。
    """
    report = DetectionReport()

    t0 = time.time()
    report.anomalies += rules.run_rule_checks(conn)
    report.stats["l0_rules"] = round(time.time() - t0, 4)

    t0 = time.time()
    report.anomalies += rules.run_consistency_checks(conn)
    report.stats["l0_cross_table"] = round(time.time() - t0, 4)

    t0 = time.time()
    watermarks = _watermarks(conn)
    report.anomalies += stats.detect_lineage_break(watermarks, Lineage())
    report.stats["l1_lineage"] = round(time.time() - t0, 4)

    t0 = time.time()
    if current_date is None:
        current_date = max(watermarks.values()) if watermarks else None
    if current_date:
        report.anomalies += stats.detect_freshness(watermarks, current_date)
    report.stats["l1_freshness"] = round(time.time() - t0, 4)

    t0 = time.time()
    if expected_schema:
        curr_schema = {
            t: {r[0]: r[1] for r in conn.execute(f"DESCRIBE {t}").fetchall()}
            for t in expected_schema
        }
        report.anomalies += stats.detect_schema_drift(curr_schema, expected_schema)
    report.stats["l1_schema"] = round(time.time() - t0, 4)

    t0 = time.time()
    report.anomalies += stats.detect_volume(conn, zscore_threshold)
    report.stats["l1_volume"] = round(time.time() - t0, 4)

    t0 = time.time()
    report.anomalies += stats.detect_distribution(conn, psi_threshold)
    report.stats["l1_distribution"] = round(time.time() - t0, 4)

    t0 = time.time()
    report.anomalies += run_semantic_checks(conn, semantic_model)
    report.stats["l2_semantic"] = round(time.time() - t0, 4)

    return report

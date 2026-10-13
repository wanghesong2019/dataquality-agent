"""检测调度：统一跑 L0/L1/L2 三层，产出 DetectionReport。"""
import time
from dataclasses import dataclass, field

import duckdb

from dataquality_agent.data.lineage import Lineage
from dataquality_agent.detection import rules, stats
from dataquality_agent.models import Anomaly


@dataclass
class DetectionReport:
    """一次巡检的结果：异常清单 + 各检查耗时（秒）。"""

    anomalies: list[Anomaly] = field(default_factory=list)
    stats: dict[str, float] = field(default_factory=dict)


def run_semantic_checks(conn) -> list[Anomaly]:
    """L2 LLM 语义检测——M1 只定义接口（stub），M2 实现 semantic.py 后接入、不改 runner。"""
    return []


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


def run_detection(conn: duckdb.DuckDBPyConnection) -> DetectionReport:
    """跑全部检测（dataset 级 → column 级，本阶段顺序简化），返回报告 + 各检查耗时。"""
    report = DetectionReport()

    t0 = time.time()
    report.anomalies += rules.run_rule_checks(conn)
    report.stats["l0_rules"] = round(time.time() - t0, 4)

    t0 = time.time()
    report.anomalies += stats.detect_lineage_break(_watermarks(conn), Lineage())
    report.stats["l1_lineage"] = round(time.time() - t0, 4)

    t0 = time.time()
    report.anomalies += run_semantic_checks(conn)
    report.stats["l2_semantic"] = round(time.time() - t0, 4)

    return report

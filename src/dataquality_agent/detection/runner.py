"""检测调度：统一跑 L0/L1/L2 三层（注册在 DETECTORS），产出 DetectionReport。"""
import time
from dataclasses import dataclass, field

from dataquality_agent.config import Settings
from dataquality_agent.data.lineage import Lineage
from dataquality_agent.detection import rules, stats
from dataquality_agent.detection.base import DETECTORS
from dataquality_agent.detection.catalog import load_assertions
from dataquality_agent.detection.semantic import run_semantic_checks
from dataquality_agent.models import Anomaly


@dataclass
class DetectionReport:
    """一次巡检的结果：异常清单 + 各检查耗时（秒；-1.0 表示该检测器失败）。"""

    anomalies: list[Anomaly] = field(default_factory=list)
    stats: dict[str, float] = field(default_factory=dict)


def _watermarks(adapter) -> dict[str, str]:
    """每表更新水位线（最新数据日期），供血缘断裂/停更检测。

    只算 orders + daily_metrics 两张表，因为它们有独立的「下单日期」轴、数据更新不依赖 FK：
    - order_items/reviews 的「最新数据」跟着 orders 走（最新订单可能还没订单项/评价，是自然现象），
      拿它们 join 出的下单日期去比 latest 订单日期会必然误报「停更」（实测如此）；
    - seller_metrics/category_metrics/payment_summary 是横截面聚合、无日期轴，无法算水位线。
    所以「数据停更」只对 orders/daily_metrics 这种有独立日期轴的表有意义。
    """
    wm: dict[str, str] = {}
    tables = set(adapter.list_tables())
    if "dwd_orders" in tables:
        rows = adapter.execute("SELECT MAX(order_purchase_timestamp::DATE) FROM dwd_orders")
        if rows and rows[0][0] is not None:
            wm["orders"] = str(rows[0][0])
    if "daily_metrics" in tables:
        rows = adapter.execute("SELECT MAX(order_date) FROM daily_metrics")
        if rows and rows[0][0] is not None:
            wm["daily_metrics"] = str(rows[0][0])
    return wm


# ---- 内置检测器（每个 = 一个可插拔步骤，detect(adapter, ctx) -> list[Anomaly]）----


class _L0Rules:
    name = "l0_rules"

    def detect(self, adapter, ctx):
        return rules.run_rule_checks(adapter, ctx["null_rate_threshold"], ctx.get("assertions"))


class _L0CrossTable:
    name = "l0_cross_table"

    def detect(self, adapter, ctx):
        return rules.run_consistency_checks(adapter)


class _L1Lineage:
    name = "l1_lineage"

    def detect(self, adapter, ctx):
        return stats.detect_lineage_break(ctx["watermarks"], Lineage())


class _L1Freshness:
    name = "l1_freshness"

    def detect(self, adapter, ctx):
        if ctx["current_date"]:
            return stats.detect_freshness(ctx["watermarks"], ctx["current_date"])
        return []


class _L1Schema:
    name = "l1_schema"

    def detect(self, adapter, ctx):
        if ctx["expected_schema"]:
            curr_schema = {t: adapter.describe_table(t) for t in ctx["expected_schema"]}
            return stats.detect_schema_drift(curr_schema, ctx["expected_schema"])
        return []


class _L1Volume:
    name = "l1_volume"

    def detect(self, adapter, ctx):
        return stats.detect_volume(adapter, ctx["zscore_threshold"], metrics=("orders", "gmv"))


class _L1Distribution:
    name = "l1_distribution"

    def detect(self, adapter, ctx):
        return stats.detect_distribution(
            adapter, ctx["distribution_alpha"],
            dimensions=(("dwd_orders", "order_status", "order_purchase_timestamp"),
                        ("dwd_reviews", "review_score", "review_creation_date")),
        )


class _L2Semantic:
    name = "l2_semantic"

    def detect(self, adapter, ctx):
        return run_semantic_checks(adapter, ctx["semantic_model"])


DETECTORS.update({
    "l0_rules": _L0Rules(),
    "l0_cross_table": _L0CrossTable(),
    "l1_lineage": _L1Lineage(),
    "l1_freshness": _L1Freshness(),
    "l1_schema": _L1Schema(),
    "l1_volume": _L1Volume(),
    "l1_distribution": _L1Distribution(),
    "l2_semantic": _L2Semantic(),
})


def run_detection(adapter, detectors=None, *,
                  current_date: str | None = None,
                  expected_schema: dict | None = None,
                  semantic_model=None,
                  zscore_threshold: float | None = None,
                  distribution_alpha: float | None = None,
                  null_rate_threshold: float | None = None,
                  assertions_path: str | None = None) -> DetectionReport:
    """跑全部检测（dataset 级 → column 级），返回报告 + 各检查耗时。

    - current_date：freshness 的参照日期（ISO 字符串）；缺省 = 数据全局最新水位线（干净数据不误报）。
    - expected_schema：schema 漂移的期望快照 {table: {col: type}}；缺省跳过 schema 检测。
    - semantic_model：L2 语义检测用的 LLM（需有 .chat）；缺省跳过 L2。
    - zscore_threshold / distribution_alpha / null_rate_threshold：缺省从 Settings 取（单一配置源）。
    - assertions_path：声明式 L0 断言目录 YAML 路径；缺省走内置 Olist 默认目录。
    - detectors：检测器注册表 {name: Detector}；缺省用内置 DETECTORS。
    单个检测器失败不拖垮整次巡检（隔离，stats[name] 记 -1.0）。
    """
    report = DetectionReport()
    dets = detectors if detectors is not None else DETECTORS

    # 共享上下文：水位线 + 参照日期 + 阈值（缺省从 Settings 取）
    watermarks = _watermarks(adapter)
    if current_date is None:
        current_date = max(watermarks.values()) if watermarks else None
    if zscore_threshold is None:
        zscore_threshold = Settings().zscore_threshold
    if distribution_alpha is None:
        distribution_alpha = Settings().distribution_alpha
    if null_rate_threshold is None:
        null_rate_threshold = Settings().null_rate_threshold

    ctx = {
        "watermarks": watermarks,
        "current_date": current_date,
        "expected_schema": expected_schema,
        "semantic_model": semantic_model,
        "zscore_threshold": zscore_threshold,
        "distribution_alpha": distribution_alpha,
        "null_rate_threshold": null_rate_threshold,
        "assertions": load_assertions(assertions_path) if assertions_path else None,
    }

    for name, det in dets.items():
        t0 = time.time()
        try:
            report.anomalies += det.detect(adapter, ctx)
        except Exception:
            report.stats[name] = -1.0  # 隔离：单检测器失败不拖垮整次巡检
        else:
            report.stats[name] = round(time.time() - t0, 4)
    return report

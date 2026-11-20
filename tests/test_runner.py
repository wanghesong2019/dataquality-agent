from dataquality_agent.adapters import DuckDBAdapter
from dataquality_agent.data.injector import Injector
from dataquality_agent.detection.base import DETECTORS
from dataquality_agent.detection.runner import run_detection


def test_run_detection_clean(mini_warehouse):
    adapter = DuckDBAdapter(Injector(mini_warehouse).connect())
    report = run_detection(adapter)
    assert report.anomalies == []
    assert {"l0_rules", "l1_lineage", "l2_semantic"} <= set(report.stats)


def test_run_detection_detects_duplicate(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    adapter = DuckDBAdapter(conn)
    inj.run(conn, [{"type": "duplicate", "table": "orders", "key_cols": ["order_id"], "n": 1}])
    report = run_detection(adapter)
    assert "duplicate" in [a.type for a in report.anomalies]
    assert report.stats["l0_rules"] >= 0


def test_run_detection_detects_freshness(mini_warehouse):
    adapter = DuckDBAdapter(Injector(mini_warehouse).connect())
    report = run_detection(adapter, current_date="2018-01-05")
    assert "freshness" in [a.type for a in report.anomalies]


def test_run_detection_detects_schema_drift(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    adapter = DuckDBAdapter(conn)
    expected = {"dwd_orders": adapter.describe_table("dwd_orders")}
    inj.run(conn, [{"type": "schema_drift", "table": "dwd_orders", "drop_column": "order_approved_at"}])
    report = run_detection(adapter, expected_schema=expected)
    assert "schema_drift" in [a.type for a in report.anomalies]


def test_run_detection_isolates_detector_failure(mini_warehouse):
    """Review Focus #2：单个检测器抛异常不拖垮整次巡检，其它检测器照常跑。"""
    adapter = DuckDBAdapter(Injector(mini_warehouse).connect())

    class Boom:
        name = "boom"

        def detect(self, adapter, ctx):
            raise RuntimeError("boom")

    detectors = dict(DETECTORS)
    detectors["boom"] = Boom()
    report = run_detection(adapter, detectors=detectors)
    assert report.stats["boom"] == -1.0  # 失败被记录
    assert "l0_rules" in report.stats       # 其它检测器照常跑
    assert report.anomalies == []           # 干净数据不误报

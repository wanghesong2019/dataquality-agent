from dataquality_agent.data.injector import Injector
from dataquality_agent.detection.runner import run_detection


def test_run_detection_clean(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    report = run_detection(conn)
    assert report.anomalies == []
    assert {"l0_rules", "l1_lineage", "l2_semantic"} <= set(report.stats)


def test_run_detection_detects_duplicate(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    inj.run(conn, [{"type": "duplicate", "table": "orders", "key_cols": ["order_id"], "n": 1}])
    report = run_detection(conn)
    assert "duplicate" in [a.type for a in report.anomalies]
    assert report.stats["l0_rules"] >= 0

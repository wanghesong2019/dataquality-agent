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


def test_run_detection_detects_freshness(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    report = run_detection(conn, current_date="2018-01-05")
    assert "freshness" in [a.type for a in report.anomalies]


def test_run_detection_detects_schema_drift(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    expected = {"dwd_orders": {r[0]: r[1] for r in conn.execute("DESCRIBE dwd_orders").fetchall()}}
    inj.run(conn, [{"type": "schema_drift", "table": "dwd_orders", "drop_column": "order_approved_at"}])
    report = run_detection(conn, expected_schema=expected)
    assert "schema_drift" in [a.type for a in report.anomalies]

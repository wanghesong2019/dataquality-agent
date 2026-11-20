import duckdb

from dataquality_agent.adapters import DuckDBAdapter
from dataquality_agent.data.lineage import Lineage
from dataquality_agent.detection.stats import (
    zscore_detect, chi2_drift, check_freshness, schema_diff, detect_lineage_break,
    detect_freshness, detect_schema_drift, detect_volume, detect_distribution,
)


def test_zscore_detect_normal_and_spike():
    baseline = [100, 105, 98, 102, 99, 101, 103]
    assert zscore_detect(100, baseline, 3.0) is False  # 接近均值，不报
    assert zscore_detect(115, baseline, 3.0) is True   # 3σ 外，报


def test_zscore_detect_constant_baseline():
    assert zscore_detect(100, [100, 100, 100], 3.0) is False


def test_chi2_drift_similar_and_shifted():
    base = {"delivered": 90, "canceled": 10}
    assert chi2_drift({"delivered": 90, "canceled": 10}, base) > 0.05
    assert chi2_drift({"delivered": 10, "canceled": 90}, base) < 0.05


def test_chi2_drift_new_category():
    assert chi2_drift({"new_type": 50, "delivered": 50}, {"delivered": 100}) == 0.0


def test_check_freshness():
    assert check_freshness(["2018-01-01", "2018-01-02", "2018-01-03"], "2018-01-03") is False
    assert check_freshness(["2018-01-01", "2018-01-02"], "2018-01-05") is True


def test_schema_diff():
    prev = {"a": "INTEGER", "b": "VARCHAR"}
    curr = {"a": "VARCHAR", "c": "INTEGER"}
    changes = schema_diff(prev, curr)
    assert "type_changed:a:INTEGER->VARCHAR" in changes
    assert "removed:b" in changes
    assert "added:c" in changes


def test_lineage_break_detected():
    lineage = Lineage()
    watermarks = {"orders": "2018-10-17", "order_items": "2018-10-17", "daily_metrics": "2018-10-10"}
    anomalies = detect_lineage_break(watermarks, lineage, max_lag_days=1)
    assert any(a.type == "lineage_break" and a.table == "daily_metrics" for a in anomalies)


def test_lineage_break_no_lag():
    lineage = Lineage()
    watermarks = {"orders": "2018-10-17", "order_items": "2018-10-17", "daily_metrics": "2018-10-17"}
    assert detect_lineage_break(watermarks, lineage, max_lag_days=1) == []


def test_detect_freshness():
    watermarks = {"orders": "2018-01-01", "daily_metrics": "2018-01-05"}
    anomalies = detect_freshness(watermarks, "2018-01-06", max_gap_days=1)
    assert {a.type: a.table for a in anomalies} == {"freshness": "orders"}


def test_detect_schema_drift():
    curr = {"dwd_orders": {"a": "INTEGER"}}
    expected = {"dwd_orders": {"a": "INTEGER", "b": "VARCHAR"}}
    anomalies = detect_schema_drift(curr, expected)
    assert len(anomalies) == 1
    assert anomalies[0].type == "schema_drift"
    assert "removed:b" in anomalies[0].summary


def _volume_adapter():
    conn = duckdb.connect()
    conn.execute("CREATE TABLE daily_metrics (order_date DATE, orders INTEGER)")
    for i in range(7):
        conn.execute("INSERT INTO daily_metrics VALUES (?, ?)", [f"2018-01-0{i + 1}", 100 + i * 5])
    conn.execute("INSERT INTO daily_metrics VALUES ('2018-01-08', 300)")  # 最后一天 spike
    return DuckDBAdapter(conn)


def test_detect_volume_spike():
    assert detect_volume(_volume_adapter(), threshold=3.0) != []   # spike 应被 z-score 检出
    assert detect_volume(_volume_adapter(), threshold=50.0) == []  # 阈值极高，不报


def _dist_adapter():
    conn = duckdb.connect()
    conn.execute("CREATE TABLE dwd_orders (order_purchase_timestamp TIMESTAMP, order_status VARCHAR)")
    for _ in range(90):
        conn.execute("INSERT INTO dwd_orders VALUES ('2018-01-01 10:00:00', 'delivered')")
    for _ in range(10):
        conn.execute("INSERT INTO dwd_orders VALUES ('2018-01-01 10:00:00', 'canceled')")
    for _ in range(100):
        conn.execute("INSERT INTO dwd_orders VALUES ('2018-01-02 10:00:00', 'canceled')")  # 最后一天全 canceled（漂移）
    return DuckDBAdapter(conn)


def test_detect_distribution_shift():
    assert detect_distribution(_dist_adapter(), alpha=0.05) != []


def _dist_adapter_similar():
    conn = duckdb.connect()
    conn.execute("CREATE TABLE dwd_orders (order_purchase_timestamp TIMESTAMP, order_status VARCHAR)")
    for day in ("2018-01-01 10:00:00", "2018-01-02 10:00:00"):
        for _ in range(90):
            conn.execute("INSERT INTO dwd_orders VALUES (?, 'delivered')", [day])
        for _ in range(10):
            conn.execute("INSERT INTO dwd_orders VALUES (?, 'canceled')", [day])
    return DuckDBAdapter(conn)


def test_detect_distribution_no_shift():
    assert detect_distribution(_dist_adapter_similar(), alpha=0.05) == []


def _dist_adapter_small_tail():
    conn = duckdb.connect()
    conn.execute("CREATE TABLE dwd_orders (order_purchase_timestamp TIMESTAMP, order_status VARCHAR)")
    for _ in range(100):
        conn.execute("INSERT INTO dwd_orders VALUES ('2018-01-01 10:00:00', 'delivered')")
    conn.execute("INSERT INTO dwd_orders VALUES ('2018-01-02 10:00:00', 'canceled')")
    return DuckDBAdapter(conn)


def test_detect_distribution_min_count_skip():
    assert detect_distribution(_dist_adapter_small_tail(), alpha=0.05) == []


def test_detect_volume_multi_metric():
    conn = duckdb.connect()
    conn.execute("CREATE TABLE daily_metrics (order_date DATE, orders INTEGER, gmv DOUBLE)")
    for i in range(7):
        conn.execute("INSERT INTO daily_metrics VALUES (?, ?, ?)",
                     [f"2018-01-0{i + 1}", 100 + i * 5, 1000.0 + i * 50])
    conn.execute("INSERT INTO daily_metrics VALUES ('2018-01-08', 300, 3000.0)")
    anomalies = detect_volume(DuckDBAdapter(conn), threshold=3.0, metrics=("orders", "gmv"))
    assert {a.column for a in anomalies} == {"orders", "gmv"}


def test_detect_distribution_multi_dim():
    conn = duckdb.connect()
    conn.execute("CREATE TABLE dwd_orders (order_purchase_timestamp TIMESTAMP, order_status VARCHAR)")
    conn.execute("CREATE TABLE dwd_reviews (review_creation_date TIMESTAMP, review_score INTEGER)")
    for _ in range(90):
        conn.execute("INSERT INTO dwd_orders VALUES ('2018-01-01 10:00:00', 'delivered')")
    for _ in range(10):
        conn.execute("INSERT INTO dwd_orders VALUES ('2018-01-01 10:00:00', 'canceled')")
    for _ in range(100):
        conn.execute("INSERT INTO dwd_orders VALUES ('2018-01-02 10:00:00', 'canceled')")
    for _ in range(90):
        conn.execute("INSERT INTO dwd_reviews VALUES ('2018-01-01 10:00:00', 5)")
    for _ in range(10):
        conn.execute("INSERT INTO dwd_reviews VALUES ('2018-01-01 10:00:00', 1)")
    for _ in range(100):
        conn.execute("INSERT INTO dwd_reviews VALUES ('2018-01-02 10:00:00', 1)")
    dims = (("dwd_orders", "order_status", "order_purchase_timestamp"),
            ("dwd_reviews", "review_score", "review_creation_date"))
    anomalies = detect_distribution(DuckDBAdapter(conn), alpha=0.05, dimensions=dims)
    assert {(a.table, a.column) for a in anomalies} == {
        ("dwd_orders", "order_status"), ("dwd_reviews", "review_score"),
    }


def test_detect_volume_min_count_skip():
    conn = duckdb.connect()
    conn.execute("CREATE TABLE daily_metrics (order_date DATE, orders INTEGER)")
    for i in range(7):
        conn.execute("INSERT INTO daily_metrics VALUES (?, ?)", [f"2018-01-0{i + 1}", 500 + i * 10])
    conn.execute("INSERT INTO daily_metrics VALUES ('2018-01-08', 1)")  # 最新一天仅 1 单
    assert detect_volume(DuckDBAdapter(conn), threshold=3.0) == []

import json

from dataquality_agent.detection.semantic import _column_profile, run_semantic_checks


def _conn_with_dwd():
    import duckdb
    conn = duckdb.connect()
    conn.execute("CREATE TABLE dwd_orders (order_id VARCHAR, order_purchase_timestamp TIMESTAMP, order_status VARCHAR)")
    conn.execute("CREATE TABLE dwd_order_items (order_id VARCHAR, price DOUBLE)")
    conn.execute("INSERT INTO dwd_orders VALUES ('o1', '2018-01-01 10:00:00', 'delivered')")
    conn.execute("INSERT INTO dwd_order_items VALUES ('o1', 10.0)")
    return conn


def _fake_model(findings):
    class FakeModel:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "", "tool_calls": [
                {"id": "1", "function": {"name": "submit_semantic_findings",
                                          "arguments": json.dumps({"findings": findings})}}
            ]}
    return FakeModel()


def test_semantic_returns_findings():
    conn = _conn_with_dwd()
    model = _fake_model([{"column": "order_status", "evidence": "枚举值可疑"}])
    anomalies = run_semantic_checks(conn, model)
    assert any(a.type == "semantic" and a.table == "dwd_orders" for a in anomalies)


def test_semantic_no_model_skips():
    assert run_semantic_checks(_conn_with_dwd(), None) == []


def test_column_profile_computes_fixed_size_metrics():
    """列画像：cardinality / null 率 / min-max / 示例值，固定大小（不随行数增长）。"""
    conn = _conn_with_dwd()
    conn.execute("INSERT INTO dwd_orders VALUES ('o1', '2018-01-02 10:00:00', 'delivered')")  # 重复 o1
    conn.execute("INSERT INTO dwd_orders VALUES ('o2', NULL, NULL)")  # null 行
    profile = _column_profile(conn, "dwd_orders", [("order_id", "VARCHAR"), ("order_status", "VARCHAR")])
    p = profile["order_id"]
    assert set(p) == {"type", "cardinality", "null_rate", "min", "max", "exemplars"}
    assert p["cardinality"] == 2  # o1, o2
    assert profile["order_status"]["null_rate"] == round(1 / 3, 4)  # 1 null / 3 rows（代码 round 到 4 位）


def test_semantic_bad_json_degrades_to_empty():
    class BadModel:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "", "tool_calls": [
                {"id": "1", "function": {"name": "submit_semantic_findings", "arguments": "not json"}}
            ]}

    assert run_semantic_checks(_conn_with_dwd(), BadModel()) == []

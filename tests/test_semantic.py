import json

from dataquality_agent.detection.semantic import run_semantic_checks


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


def test_semantic_bad_json_degrades_to_empty():
    class BadModel:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "", "tool_calls": [
                {"id": "1", "function": {"name": "submit_semantic_findings", "arguments": "not json"}}
            ]}

    assert run_semantic_checks(_conn_with_dwd(), BadModel()) == []

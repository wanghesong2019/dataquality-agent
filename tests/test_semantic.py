import json

from dataquality_agent.detection.semantic import _column_profile, _parse_findings, run_semantic_checks


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


def _real_tool_call(name, arguments):
    """模拟 DeepSeek/OpenAI 真实的 tool_call 元素：type=function + function.name/arguments。"""
    return {"id": "call_abc123", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}


def test_parse_findings_real_tool_call():
    """真实格式：tool_call 含 type=function，arguments 是 JSON 字符串，正确取出 findings。"""
    resp = {"content": "", "tool_calls": [
        _real_tool_call("submit_semantic_findings",
                        {"findings": [{"column": "order_status", "evidence": "枚举可疑"}]})
    ]}
    assert _parse_findings(resp) == [{"column": "order_status", "evidence": "枚举可疑"}]


def test_parse_findings_empty_findings():
    """findings 为空列表 → 返回空。"""
    resp = {"content": "", "tool_calls": [_real_tool_call("submit_semantic_findings", {"findings": []})]}
    assert _parse_findings(resp) == []


def test_parse_findings_picks_target_among_multiple_calls():
    """多个 tool_call 里只挑 submit_semantic_findings，忽略其它工具。"""
    resp = {"content": "", "tool_calls": [
        _real_tool_call("other_tool", {"x": 1}),
        _real_tool_call("submit_semantic_findings", {"findings": [{"column": "price", "evidence": "负值"}]}),
    ]}
    assert _parse_findings(resp) == [{"column": "price", "evidence": "负值"}]


def test_parse_findings_no_tool_calls():
    """模型没调工具（纯文本回复）→ 空列表。"""
    resp = {"content": "没发现问题", "tool_calls": []}
    assert _parse_findings(resp) == []


def test_parse_findings_missing_findings_key_defaults_empty():
    """arguments 里没有 findings 键 → .get 默认空列表。"""
    resp = {"content": "", "tool_calls": [_real_tool_call("submit_semantic_findings", {"other": 1})]}
    assert _parse_findings(resp) == []


def test_parse_findings_bad_json_degrades_empty():
    """arguments 不是合法 JSON → 降级空列表。"""
    resp = {"content": "", "tool_calls": [
        {"id": "call_x", "type": "function",
         "function": {"name": "submit_semantic_findings", "arguments": "not json"}}
    ]}
    assert _parse_findings(resp) == []


def test_semantic_bad_json_degrades_to_empty():
    class BadModel:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "", "tool_calls": [
                {"id": "1", "function": {"name": "submit_semantic_findings", "arguments": "not json"}}
            ]}

    assert run_semantic_checks(_conn_with_dwd(), BadModel()) == []

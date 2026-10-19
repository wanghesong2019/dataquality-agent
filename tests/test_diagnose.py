import json

from dataquality_agent.agents.diagnose import make_diagnose_node
from dataquality_agent.models import Anomaly
from dataquality_agent.prompts import Tool


def _lineage_tool():
    def func(args):
        return f"{args['table']} 的上游是 orders"

    return Tool(name="lineage", description="查表的上游血缘",
                parameters={"type": "object", "properties": {"table": {"type": "string"}}, "required": ["table"]},
                func=func)


def _call(name, args):
    return {"id": "1", "function": {"name": name, "arguments": json.dumps(args)}}


def test_diagnose_reasoning_loop():
    calls = []

    class FakeModel:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            calls.append(messages)
            if len(calls) == 1:
                return {"content": "", "tool_calls": [_call("lineage", {"table": "order_items"})]}
            return {"content": "", "tool_calls": [_call("submit_diagnosis",
                    {"root_cause_category": "上游任务失败", "confidence": 0.9})]}

    node = make_diagnose_node(FakeModel(), [_lineage_tool()])
    result = node({"anomalies": [Anomaly(type="orphan", table="order_items")]})
    d = result["diagnoses"][0]
    assert d.root_cause_category == "上游任务失败"
    assert d.confidence == 0.9
    assert len(d.evidence_chain) == 1  # 用了一次工具


def test_diagnose_max_steps_fallback():
    class FakeModel:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "", "tool_calls": [_call("lineage", {"table": "order_items"})]}

    node = make_diagnose_node(FakeModel(), [_lineage_tool()], max_steps=2)
    result = node({"anomalies": [Anomaly(type="orphan", table="order_items")]})
    assert result["diagnoses"][0].root_cause_category == "未知"


def test_diagnose_ignores_model_evidence_chain():
    """模型自述 evidence_chain 时不得重复传关键字（否则 TypeError 被误降级为「未知」）。"""
    calls = []

    class FakeModel:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            calls.append(1)
            if len(calls) == 1:
                return {"content": "", "tool_calls": [_call("lineage", {"table": "orders"})]}
            return {"content": "", "tool_calls": [_call("submit_diagnosis", {
                "root_cause_category": "脏数据注入", "confidence": 0.8,
                "evidence_chain": ["模型自述的假证据"]})]}

    node = make_diagnose_node(FakeModel(), [_lineage_tool()])
    result = node({"anomalies": [Anomaly(type="duplicate", table="orders")]})
    d = result["diagnoses"][0]
    assert d.root_cause_category == "脏数据注入"  # 正确解析，不 fallback
    assert len(d.evidence_chain) == 1  # 以实际工具调用历史为准（1 次 lineage）


def _cases_tool():
    matched_ids = []

    def func(args):
        matched_ids.append("dup_orders")
        return "[{'id': 'dup_orders', 'text': '订单主键重复'}]"

    tool = Tool(name="cases", description="检索相似案例",
                parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                func=func)
    tool.matched_case_ids = matched_ids
    return tool


def test_diagnose_backfills_matched_cases_from_cases_tool():
    """matched_cases 以 cases 工具真实命中为准，丢弃模型自述（同 evidence_chain 防幻觉）。"""
    calls = []

    class FakeModel:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            calls.append(1)
            if len(calls) == 1:
                return {"content": "", "tool_calls": [_call("cases", {"query": "重复"})]}
            return {"content": "", "tool_calls": [_call("submit_diagnosis", {
                "root_cause_category": "脏数据注入", "confidence": 0.8,
                "matched_cases": ["模型自述的假案例ID"]})]}

    node = make_diagnose_node(FakeModel(), [_cases_tool()])
    result = node({"anomalies": [Anomaly(type="duplicate", table="orders")]})
    d = result["diagnoses"][0]
    assert d.matched_cases == ["dup_orders"]  # 真实命中，不是模型自述的假 ID

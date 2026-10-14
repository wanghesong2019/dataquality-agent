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

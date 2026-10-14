import json

from dataquality_agent.agents.remediate import make_remediate_node
from dataquality_agent.models import Diagnosis


def _tool_call(name, args):
    return {"id": "1", "function": {"name": name, "arguments": json.dumps(args)}}


def test_remediate_node_high_risk():
    class FakeModel:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "", "tool_calls": [_tool_call("submit_remediation", {
                "action_type": "fix_sql", "sql_or_suggestion": "DELETE 重复行", "risk_level": "high"})]}

    node = make_remediate_node(FakeModel())
    result = node({"diagnoses": [Diagnosis(root_cause_category="dup_rows", confidence=0.9)]})
    assert len(result["remediations"]) == 1
    r = result["remediations"][0]
    assert r.action_type == "fix_sql"
    assert r.requires_approval is True  # 高危 → 必须审批


def test_remediate_node_low_risk():
    class FakeModel:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "", "tool_calls": [_tool_call("submit_remediation", {
                "action_type": "add_rule", "sql_or_suggestion": "price > 0", "risk_level": "low"})]}

    node = make_remediate_node(FakeModel())
    result = node({"diagnoses": [Diagnosis(root_cause_category="value_range", confidence=0.8)]})
    assert result["remediations"][0].requires_approval is False  # 低危 → 自动执行


def test_remediate_node_bad_response_degrades():
    class FakeModel:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "抱歉我不会", "tool_calls": []}

    node = make_remediate_node(FakeModel())
    result = node({"diagnoses": [Diagnosis(root_cause_category="x", confidence=0.5)]})
    # 没调 submit_remediation → 降级为默认 ticket/low
    r = result["remediations"][0]
    assert r.action_type == "ticket"
    assert r.risk_level == "low"

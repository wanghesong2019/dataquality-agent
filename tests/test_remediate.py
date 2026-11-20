import json

from dataquality_agent.agents.remediate import _rule_check, make_remediate_node
from dataquality_agent.models import Anomaly, Diagnosis, Remediation


def _tool_call(name, args):
    return {"id": "1", "function": {"name": name, "arguments": json.dumps(args)}}


def _state(anomaly, diagnosis):
    return {"anomalies": [anomaly], "diagnoses": [diagnosis]}


class FakeAdapter:
    def list_tables(self):
        return ["orders", "order_items"]


class FakeModel:
    """按 tool_choice 区分 Executor / Critic 两个角色：分别回 submit_remediation / submit_critique。"""

    def __init__(self, remediation, verdict=None):
        self.remediation = remediation
        self.verdict = verdict or {"passed": True, "feedback": ""}

    def chat(self, messages, tools=None, tool_choice=None, response_format=None):
        name = (tool_choice or {}).get("function", {}).get("name")
        if name == "submit_critique":
            return {"content": "", "tool_calls": [_tool_call("submit_critique", self.verdict)]}
        return {"content": "", "tool_calls": [_tool_call("submit_remediation", self.remediation)]}


def test_remediate_node_high_risk():
    model = FakeModel({
        "action_type": "fix_sql",
        "sql_or_suggestion": "DELETE FROM orders WHERE order_id IN (SELECT order_id FROM orders GROUP BY order_id HAVING COUNT(*) > 1)",
        "risk_level": "high",
    })
    node = make_remediate_node(model, FakeAdapter())
    result = node(_state(Anomaly(type="duplicate", table="orders"),
                         Diagnosis(root_cause_category="脏数据注入", confidence=0.9)))
    r = result["remediations"][0]
    assert r.action_type == "fix_sql"
    assert r.requires_approval is True  # 高危 → 必须审批


def test_remediate_node_low_risk():
    model = FakeModel({"action_type": "add_rule", "sql_or_suggestion": "price > 0", "risk_level": "low"})
    node = make_remediate_node(model, FakeAdapter())
    result = node(_state(Anomaly(type="value_range", table="order_items", column="price"),
                         Diagnosis(root_cause_category="脏数据注入", confidence=0.8)))
    assert result["remediations"][0].requires_approval is False  # 低危 → 自动执行


def test_remediate_node_bad_response_degrades():
    class BadModel:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "抱歉我不会", "tool_calls": []}

    node = make_remediate_node(BadModel(), FakeAdapter())
    result = node(_state(Anomaly(type="orphan", table="order_items"),
                         Diagnosis(root_cause_category="上游任务失败", confidence=0.5)))
    r = result["remediations"][0]
    assert r.action_type == "ticket"
    assert r.risk_level == "low"


def test_rule_check_missing_where():
    c = Remediation(action_type="fix_sql", sql_or_suggestion="DELETE FROM orders", risk_level="high")
    failures = _rule_check(c, {"orders"})
    assert any("WHERE" in f for f in failures)


def test_rule_check_risk_mismatch():
    c = Remediation(action_type="fix_sql", sql_or_suggestion="DELETE FROM orders WHERE order_id = 1", risk_level="low")
    failures = _rule_check(c, {"orders"})
    assert any("high" in f for f in failures)

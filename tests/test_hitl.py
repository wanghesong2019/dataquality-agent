from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from dataquality_agent.agents.graph import build_graph
from dataquality_agent.agents.hitl import make_approve_node, needs_approval
from dataquality_agent.models import Anomaly, Diagnosis, Remediation, Report


def test_needs_approval():
    assert needs_approval([Remediation(action_type="fix_sql", sql_or_suggestion="x", risk_level="high")]) is True
    assert needs_approval([Remediation(action_type="add_rule", sql_or_suggestion="x", risk_level="low")]) is False
    assert needs_approval([]) is False


def test_approve_node_no_high_risk():
    node = make_approve_node()
    result = node({"remediations": [Remediation(action_type="add_rule", sql_or_suggestion="x", risk_level="low")]})
    assert result["approvals"] == []


def test_high_risk_interrupt_and_resume():
    def inspect(state):
        return {"anomalies": [Anomaly(type="orphan", table="order_items")]}

    def diagnose(state):
        return {"diagnoses": [Diagnosis(root_cause_category="upstream_del", confidence=0.9)]}

    def remediate(state):
        return {"remediations": [Remediation(action_type="fix_sql", sql_or_suggestion="DELETE", risk_level="high")]}

    def report(state):
        return {"report": Report(summary="done")}

    graph = build_graph(inspect, diagnose, remediate, make_approve_node(), report, checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "hitl-test"}}
    first = graph.invoke({}, config)
    # 停在了 approve 节点（interrupt），report 还没产出
    assert first.get("report") is None
    # 人工恢复：批准第 0 条整改
    resumed = graph.invoke(Command(resume={"0": "approved"}), config)
    assert resumed["report"].summary == "done"
    assert resumed["approvals"][0].decision == "approved"

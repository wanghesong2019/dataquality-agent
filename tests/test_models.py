from dataquality_agent.models import Diagnosis, Remediation, AgentState


def test_diagnosis_model():
    d = Diagnosis(root_cause_category="upstream_task_failed", confidence=0.9,
                  evidence_chain=["orders 停更", "daily_metrics 为空"])
    assert d.root_cause_category == "upstream_task_failed"
    assert d.confidence == 0.9
    assert len(d.evidence_chain) == 2


def test_remediation_requires_approval_by_risk():
    high = Remediation(action_type="fix_sql", sql_or_suggestion="DELETE ...", risk_level="high")
    low = Remediation(action_type="add_rule", sql_or_suggestion="price > 0", risk_level="low")
    assert high.requires_approval is True
    assert low.requires_approval is False


def test_agent_state_shape():
    state: AgentState = {"run_id": "r1", "anomalies": [], "loop_count": 0}
    assert state["run_id"] == "r1"
    assert state["loop_count"] == 0

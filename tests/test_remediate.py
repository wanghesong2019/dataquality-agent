import json

from dataquality_agent.agents.remediate import make_remediate_node
from dataquality_agent.models import Diagnosis


def test_remediate_node_high_risk():
    def fake_model(prompt):
        return json.dumps({
            "action_type": "fix_sql",
            "sql_or_suggestion": "DELETE 重复行",
            "risk_level": "high",
        })

    node = make_remediate_node(fake_model)
    result = node({"diagnoses": [Diagnosis(root_cause_category="dup_rows", confidence=0.9)]})

    assert len(result["remediations"]) == 1
    r = result["remediations"][0]
    assert r.action_type == "fix_sql"
    assert r.requires_approval is True  # 高危 → 必须审批


def test_remediate_node_low_risk():
    def fake_model(prompt):
        return json.dumps({
            "action_type": "add_rule",
            "sql_or_suggestion": "price > 0",
            "risk_level": "low",
        })

    node = make_remediate_node(fake_model)
    result = node({"diagnoses": [Diagnosis(root_cause_category="value_range", confidence=0.8)]})

    assert result["remediations"][0].requires_approval is False  # 低危 → 自动执行

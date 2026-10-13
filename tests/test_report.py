from dataquality_agent.agents.report import make_report_node
from dataquality_agent.models import Anomaly, Remediation


def test_report_node():
    def fake_model(prompt):
        return "发现 2 个异常"

    node = make_report_node(fake_model)
    result = node({
        "anomalies": [Anomaly(type="dup", table="orders"), Anomaly(type="orphan", table="items")],
        "remediations": [Remediation(action_type="ticket", sql_or_suggestion="x")],
    })
    assert result["report"].anomaly_count == 2
    assert result["report"].remediation_count == 1
    assert result["report"].summary == "发现 2 个异常"

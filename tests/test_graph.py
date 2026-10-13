from dataquality_agent.agents.graph import build_graph
from dataquality_agent.models import Anomaly, Diagnosis, Remediation, Report


def test_graph_flow():
    def inspect(state):
        return {"anomalies": [Anomaly(type="duplicate", table="orders")]}

    def diagnose(state):
        return {"diagnoses": [Diagnosis(root_cause_category="dup_rows", confidence=0.9)]}

    def remediate(state):
        return {"remediations": [Remediation(action_type="ticket", sql_or_suggestion="去重")]}

    def report(state):
        return {"report": Report(summary="done", anomaly_count=len(state.get("anomalies", [])))}

    graph = build_graph(inspect, diagnose, remediate, report)
    result = graph.invoke({"run_id": "r1"})
    assert len(result["anomalies"]) == 1
    assert len(result["diagnoses"]) == 1
    assert len(result["remediations"]) == 1
    assert result["report"].anomaly_count == 1

import json

from dataquality_agent.agents.diagnose import make_diagnose_node
from dataquality_agent.models import Anomaly


def test_diagnose_reasoning_loop():
    calls = []

    def fake_model(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return "TOOL:lineage:order_items"
        return json.dumps({"root_cause_category": "upstream_task_failed", "confidence": 0.9})

    tools = {"lineage": lambda arg: f"{arg} 的上游是 orders"}

    node = make_diagnose_node(fake_model, tools)
    result = node({"anomalies": [Anomaly(type="orphan", table="order_items")]})

    assert len(result["diagnoses"]) == 1
    d = result["diagnoses"][0]
    assert d.root_cause_category == "upstream_task_failed"
    assert d.confidence == 0.9
    assert len(d.evidence_chain) == 1  # 用了一次工具


def test_diagnose_max_steps_fallback():
    def always_tool(prompt):
        return "TOOL:lineage:order_items"

    node = make_diagnose_node(always_tool, {"lineage": lambda a: "x"}, max_steps=2)
    result = node({"anomalies": [Anomaly(type="orphan", table="order_items")]})
    assert result["diagnoses"][0].root_cause_category == "unknown"

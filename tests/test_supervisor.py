"""§13：Supervisor 分诊节点的单元测试 + 完整图集成测试。"""
import json

from dataquality_agent.agents.supervisor import make_triage_node
from dataquality_agent.models import Anomaly


def _model_triage(assignments):
    class FakeModel:
        def __init__(self):
            self.tracer = None

        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "", "tool_calls": [
                {"id": "1", "function": {"name": "submit_triage", "arguments": json.dumps({"assignments": assignments})}}
            ]}
    return FakeModel()


def _model_diagnosis():
    class FakeModel:
        def __init__(self):
            self.tracer = None

        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "", "tool_calls": [
                {"id": "1", "function": {"name": "submit_diagnosis",
                                         "arguments": json.dumps({"root_cause_category": "脏数据注入", "confidence": 0.9})}}
            ]}
    return FakeModel()


def _model_invalid():
    class FakeModel:
        def __init__(self):
            self.tracer = None

        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "", "tool_calls": []}  # 无工具调用 → LLM 无效
    return FakeModel()


def _anomalies():
    return [
        Anomaly(type="orphan", table="order_items"),
        Anomaly(type="duplicate", table="orders"),
        Anomaly(type="value_range", table="order_items"),
    ]


def test_triage_llm_assigns():
    node = make_triage_node(_model_triage(["lineage", "sql", "sql"]))
    result = node({"anomalies": _anomalies()})
    assert result["assignments"] == ["lineage", "sql", "sql"]
    assert result["findings"] == ["", "", ""]


def test_triage_fallback_on_invalid_llm():
    """LLM 无工具调用 → 确定性映射：orphan→lineage，其余→sql。"""
    node = make_triage_node(_model_invalid())
    result = node({"anomalies": _anomalies()})
    assert result["assignments"] == ["lineage", "sql", "sql"]


def test_triage_fallback_on_bad_value():
    """LLM 返回非法值 → 落确定性映射（bad → lineage）。"""
    node = make_triage_node(_model_triage(["bad", "sql", "cases"]))
    result = node({"anomalies": _anomalies()})
    assert result["assignments"] == ["lineage", "sql", "cases"]


def test_aggregate_diagnose_node():
    """聚合诊断节点：读 findings（每个异常一条），按行拆成 evidence_chain → Diagnosis。"""
    from dataquality_agent.agents.diagnose import make_aggregate_diagnose_node

    node = make_aggregate_diagnose_node(_model_diagnosis())
    state = {
        "anomalies": [Anomaly(type="duplicate", table="orders")],
        "findings": ["schema(orders) -> {order_id: VARCHAR}\nsql(...) -> 3 rows"],
    }
    result = node(state)
    assert result["diagnoses"][0].root_cause_category == "脏数据注入"
    assert len(result["diagnoses"][0].evidence_chain) == 2  # 两行 finding 拆成两条证据


def test_supervisor_graph_routes_to_assigned_specialist():
    """集成：完整图跑通，专职 Agent 只处理分给自己的异常（线性 triage→lineage→sql→cases→diagnose）。"""
    from dataquality_agent.agents.graph import build_supervisor_graph

    def inspect(state):
        return {"anomalies": [Anomaly(type="orphan", table="order_items"),
                              Anomaly(type="duplicate", table="orders")]}

    def triage(state):
        return {"assignments": ["lineage", "sql"], "findings": ["", ""]}

    def lineage(state):
        findings = list(state["findings"])
        if state["assignments"][0] == "lineage":
            findings[0] = "lineage(order_items) -> [orders, products]"
        return {"findings": findings}

    def sql(state):
        findings = list(state["findings"])
        if state["assignments"][1] == "sql":
            findings[1] = "sql(orders) -> 3 dup rows"
        return {"findings": findings}

    def cases(state):
        return {"findings": state["findings"]}  # 无分配 → no-op

    def diagnose(state):
        return {"diagnoses": state["findings"]}

    def remediate(state):
        return {"remediations": []}

    def approve(state):
        return {"approvals": []}

    def report(state):
        return {"report": "ok"}

    graph = build_supervisor_graph(inspect, triage, lineage, sql, cases, diagnose,
                                   remediate, approve, report)
    result = graph.invoke({"run_id": "r1"})
    assert result["findings"] == ["lineage(order_items) -> [orders, products]", "sql(orders) -> 3 dup rows"]
    assert result["report"] == "ok"

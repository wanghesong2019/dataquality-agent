"""薄归因（确定性证据装配 + 单一 LLM 调用）的单元测试。"""
import json

from dataquality_agent.adapters import DuckDBAdapter
from dataquality_agent.data.injector import Injector
from dataquality_agent.data.lineage import Lineage
from dataquality_agent.models import Anomaly, Evidence
from dataquality_agent.rag.cases import build_retriever


def _adapter(mini_warehouse):
    return DuckDBAdapter(Injector(mini_warehouse).connect())


def test_assemble_evidence_is_deterministic(mini_warehouse):
    from dataquality_agent.agents.diagnose import assemble_evidence

    adapter = _adapter(mini_warehouse)
    lineage = Lineage()
    retriever = build_retriever()
    a = Anomaly(type="duplicate", table="orders", column="order_id",
                evidence=Evidence(query="SELECT * FROM orders WHERE order_id IN (...)",
                                  rows=[{"order_id": "o1"}]))
    p1 = assemble_evidence(a, adapter, lineage, retriever)
    p2 = assemble_evidence(a, adapter, lineage, retriever)
    assert p1 == p2 and p1, "证据装配确定性且非空"


def test_thin_diagnose_degrades_on_empty_evidence(mini_warehouse):
    from dataquality_agent.agents.diagnose import make_thin_diagnose_node

    class FakeModel:
        tracer = None

        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            raise AssertionError("空证据不应调用 LLM")

    node = make_thin_diagnose_node(FakeModel(), _adapter(mini_warehouse), Lineage(), build_retriever())
    a = Anomaly(type="weird", table="nope", evidence=Evidence(query="", rows=None))
    out = node({"anomalies": [a]})
    assert out["diagnoses"][0].root_cause_category == "未知"  # 空证据 → 优雅降级，不崩、不调 LLM


def test_thin_diagnose_returns_diagnosis_with_evidence(mini_warehouse):
    from dataquality_agent.agents.diagnose import make_thin_diagnose_node

    class FakeModel:
        tracer = None

        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "", "tool_calls": [
                {"id": "1", "function": {"name": "submit_diagnosis",
                                         "arguments": json.dumps({"root_cause_category": "脏数据注入",
                                                                  "confidence": 0.9})}}
            ]}

    node = make_thin_diagnose_node(FakeModel(), _adapter(mini_warehouse), Lineage(), build_retriever())
    a = Anomaly(type="duplicate", table="orders", column="order_id",
                evidence=Evidence(query="SELECT * FROM orders WHERE ...", rows=[{"order_id": "o1"}]))
    out = node({"anomalies": [a]})
    d = out["diagnoses"][0]
    assert d.root_cause_category == "脏数据注入"
    assert isinstance(d.evidence, list) and isinstance(d.evidence[0], Evidence)

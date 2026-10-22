"""§13 Phase 1：3 个专职 Agent 的单元测试。"""
import json

from dataquality_agent.agents.specialists import make_cases_agent, make_lineage_agent, make_sql_agent
from dataquality_agent.models import Anomaly


class FakeLineage:
    def upstream(self, table):
        return ["orders", "products"]


class FakeRetriever:
    def search(self, query, k=3):
        return [{"id": "orphan_items", "text": "孤儿外键"}]


class FakeResult:
    def fetchall(self):
        return [("orders",), ("order_items",)]


class FakeConn:
    def execute(self, sql):
        return FakeResult()


def _model_with_tool_call(tool_name, args):
    """FakeModel：第一次 chat 返回一次工具调用，之后返回空（让聚焦循环 break）。"""
    class FakeModel:
        def __init__(self):
            self.tracer = None
            self._called = False

        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            if self._called:
                return {"content": "", "tool_calls": []}
            self._called = True
            return {"content": "", "tool_calls": [
                {"id": "1", "function": {"name": tool_name, "arguments": json.dumps(args)}}
            ]}
    return FakeModel()


def test_lineage_agent_produces_finding():
    node = make_lineage_agent(_model_with_tool_call("lineage", {"table": "order_items"}), FakeLineage())
    result = node({"anomalies": [Anomaly(type="orphan", table="order_items")]})
    assert len(result["lineage_findings"]) == 1
    assert "orders" in result["lineage_findings"][0]


def test_cases_agent_produces_finding():
    node = make_cases_agent(_model_with_tool_call("cases", {"query": "孤儿"}), FakeRetriever())
    result = node({"anomalies": [Anomaly(type="orphan", table="order_items")]})
    assert len(result["cases_findings"]) == 1
    assert "orphan_items" in result["cases_findings"][0]


def test_sql_agent_produces_finding():
    node = make_sql_agent(_model_with_tool_call("schema", {"table": "orders"}), FakeConn())
    result = node({"anomalies": [Anomaly(type="duplicate", table="orders")]})
    assert len(result["sql_findings"]) == 1
    assert "schema" in result["sql_findings"][0]

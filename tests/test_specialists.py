"""§13：3 个专职 Agent 的单元测试（只处理分诊指派给自己的异常）。"""
import json

from dataquality_agent.agents.specialists import make_cases_agent, make_lineage_agent, make_sql_agent
from dataquality_agent.models import Anomaly


class FakeLineage:
    def upstream(self, table):
        return ["orders", "products"]


class FakeRetriever:
    def search(self, query, k=3):
        return [{"id": "orphan_items", "text": "孤儿外键"}]


class FakeAdapter:
    def list_tables(self):
        return ["orders", "order_items"]

    def describe_table(self, table):
        return {"order_id": "VARCHAR"}


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


def _state(assignments):
    return {
        "anomalies": [Anomaly(type="orphan", table="order_items")],
        "assignments": assignments,
        "findings": [""],
    }


def test_lineage_agent_processes_assigned():
    node = make_lineage_agent(_model_with_tool_call("lineage", {"table": "order_items"}), FakeLineage())
    result = node(_state(["lineage"]))
    assert "orders" in result["findings"][0]


def test_lineage_agent_skips_unassigned():
    """未分给 lineage → 不处理，finding 保持空。"""
    node = make_lineage_agent(_model_with_tool_call("lineage", {"table": "order_items"}), FakeLineage())
    result = node(_state(["sql"]))
    assert result["findings"][0] == ""


def test_cases_agent_processes_assigned():
    node = make_cases_agent(_model_with_tool_call("cases", {"query": "孤儿"}), FakeRetriever())
    result = node(_state(["cases"]))
    assert "orphan_items" in result["findings"][0]


def test_sql_agent_processes_assigned():
    node = make_sql_agent(_model_with_tool_call("schema", {"table": "orders"}), FakeAdapter())
    result = node(_state(["sql"]))
    assert "schema" in result["findings"][0]

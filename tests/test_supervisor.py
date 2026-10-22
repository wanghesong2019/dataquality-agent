"""§13 Phase 2：Supervisor 分诊节点的单元测试。"""
import json

from dataquality_agent.agents.supervisor import make_supervisor_node
from dataquality_agent.models import Anomaly


def _model_returning_route(route):
    class FakeModel:
        def __init__(self):
            self.tracer = None

        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "", "tool_calls": [
                {"id": "1", "function": {"name": "submit_route", "arguments": json.dumps({"route": route})}}
            ]}
    return FakeModel()


def _model_invalid():
    class FakeModel:
        def __init__(self):
            self.tracer = None

        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "", "tool_calls": []}  # 无工具调用 → LLM 无效
    return FakeModel()


def _state(history=None):
    return {"anomalies": [Anomaly(type="duplicate", table="orders")], "route_history": history or []}


def test_supervisor_llm_route():
    node = make_supervisor_node(_model_returning_route("sql"))
    result = node(_state())
    assert result["route"] == "sql"
    assert result["route_history"] == ["sql"]


def test_supervisor_fallback_on_invalid_llm():
    """LLM 无工具调用 → 兜底取第一个 unvisited（lineage）。"""
    node = make_supervisor_node(_model_invalid())
    result = node(_state())
    assert result["route"] == "lineage"


def test_supervisor_fallback_on_visited_route():
    """LLM 返回已派过的 sql → 兜底取第一个 unvisited（lineage）。"""
    node = make_supervisor_node(_model_returning_route("sql"))
    result = node(_state(history=["sql"]))
    assert result["route"] == "lineage"


def test_supervisor_done_when_all_visited():
    """全派过 → 强制 done（保证终止）。"""
    node = make_supervisor_node(_model_returning_route("sql"))
    result = node(_state(history=["lineage", "sql", "cases"]))
    assert result["route"] == "done"


def test_supervisor_graph_runs_and_terminates():
    """集成：build_supervisor_graph 循环能跑通并终止（fallback 分诊 lineage→sql→cases→done）。"""
    from dataquality_agent.agents.graph import build_supervisor_graph

    def inspect(state):
        return {"anomalies": [Anomaly(type="duplicate", table="orders")]}

    def lineage(state):
        return {"lineage_findings": ["lineage(orders) -> []"]}

    def sql(state):
        return {"sql_findings": ["schema(orders) -> {order_id: VARCHAR}"]}

    def cases(state):
        return {"cases_findings": ["cases(重复) -> [dup_orders]"]}

    graph = build_supervisor_graph(inspect, make_supervisor_node(_model_invalid()), lineage, sql, cases)
    result = graph.invoke({"run_id": "r1"})
    assert result["route"] == "done"
    assert result["route_history"] == ["lineage", "sql", "cases"]
    assert result["lineage_findings"] and result["sql_findings"] and result["cases_findings"]

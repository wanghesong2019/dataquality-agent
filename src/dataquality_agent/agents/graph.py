"""LangGraph 状态机骨架：巡检 → 归因 → 整改 → 报告（HITL 审批后续加）。"""
from langgraph.graph import END, StateGraph

from dataquality_agent.models import AgentState


def build_graph(inspect_fn, diagnose_fn, remediate_fn, report_fn):
    """构建并编译图。节点函数签名：fn(state) -> dict（部分状态更新）。"""
    g = StateGraph(AgentState)
    g.add_node("inspect", inspect_fn)
    g.add_node("diagnose", diagnose_fn)
    g.add_node("remediate", remediate_fn)
    g.add_node("report", report_fn)
    g.set_entry_point("inspect")
    g.add_edge("inspect", "diagnose")
    g.add_edge("diagnose", "remediate")
    g.add_edge("remediate", "report")
    g.add_edge("report", END)
    return g.compile()

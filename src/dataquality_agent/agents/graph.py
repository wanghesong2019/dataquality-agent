"""LangGraph 状态机：巡检 → 归因 → 整改 → (HITL 审批) → 报告。"""
from langgraph.graph import END, StateGraph

from dataquality_agent.models import AgentState


def _route(state) -> str:
    """整改后有高危方案 → 走审批；否则直接报告。"""
    if any(r.requires_approval for r in state.get("remediations", [])):
        return "approve"
    return "report"


def build_graph(inspect_fn, diagnose_fn, remediate_fn, approve_fn, report_fn, checkpointer=None):
    """构建并编译图。节点函数签名：fn(state) -> dict（部分状态更新）。
    checkpointer 用于 HITL 暂停/恢复（interrupt 需要持久化状态）。"""
    g = StateGraph(AgentState)
    g.add_node("inspect", inspect_fn)
    g.add_node("diagnose", diagnose_fn)
    g.add_node("remediate", remediate_fn)
    g.add_node("approve", approve_fn)
    g.add_node("report", report_fn)
    g.set_entry_point("inspect")
    g.add_edge("inspect", "diagnose")
    g.add_edge("diagnose", "remediate")
    g.add_conditional_edges("remediate", _route, {"approve": "approve", "report": "report"})
    g.add_edge("approve", "report")
    g.add_edge("report", END)
    return g.compile(checkpointer=checkpointer)

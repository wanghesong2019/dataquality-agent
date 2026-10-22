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


def _route_supervisor(state) -> str:
    """Supervisor 分诊的 conditional edge：按 state.route 路由（缺省 done）。"""
    return state.get("route", "done")


def build_supervisor_graph(inspect_fn, supervisor_fn, lineage_agent, sql_agent, cases_agent):
    """构建 Supervisor 循环图（§13 Phase 2）：inspect → supervisor ↕{lineage,sql,cases} → done。

    Phase 2 只接循环，done 先到 END；Phase 3 再接 diagnose 聚合 + remediate/approve/report。
    """
    g = StateGraph(AgentState)
    g.add_node("inspect", inspect_fn)
    g.add_node("supervisor", supervisor_fn)
    g.add_node("lineage", lineage_agent)
    g.add_node("sql", sql_agent)
    g.add_node("cases", cases_agent)
    g.set_entry_point("inspect")
    g.add_edge("inspect", "supervisor")
    g.add_conditional_edges("supervisor", _route_supervisor, {
        "lineage": "lineage",
        "sql": "sql",
        "cases": "cases",
        "done": END,
    })
    g.add_edge("lineage", "supervisor")
    g.add_edge("sql", "supervisor")
    g.add_edge("cases", "supervisor")
    return g.compile()

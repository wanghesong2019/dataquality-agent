"""Supervisor 分诊节点（§13 Phase 2）：LLM 决定下一步派哪个专职 Agent，或 done。

robust 设计（三道兜底，对应文档 §13「分诊」）：
① LLM 无效/超时 → 确定性 round-robin（按 lineage→sql→cases 取第一个没跑过的）；
② route 只允许 {lineage,sql,cases,done}（结构化 schema 约束），非法值/已跑过的落兜底；
③ 全部派过 → 强制 done（保证终止，不无限循环）。
"""
import json

from dataquality_agent.observability.tracing import trace_step
from dataquality_agent.prompts import SUBMIT_ROUTE_SCHEMA, build_supervisor_prompt

_SPECIALIST_KEYS = {"lineage": "lineage_findings", "sql": "sql_findings", "cases": "cases_findings"}


def _fallback_route(unvisited: list[str]) -> str:
    """确定性兜底：取第一个没跑过的专职 Agent；都跑过则 done（防御，正常到不了）。"""
    return unvisited[0] if unvisited else "done"


def _llm_route(model, anomalies, findings: dict, unvisited: list[str]) -> str | None:
    """LLM 分诊：读异常 + 已收集 findings，决定下一个 unvisited 专职 Agent 或 done。"""
    resp = model.chat(
        [{"role": "user", "content": build_supervisor_prompt(anomalies, findings, unvisited)}],
        tools=[SUBMIT_ROUTE_SCHEMA],
        tool_choice={"type": "function", "function": {"name": "submit_route"}},
    )
    for call in (resp or {}).get("tool_calls", []):
        if call.get("function", {}).get("name") == "submit_route":
            try:
                return json.loads(call["function"]["arguments"]).get("route")
            except (json.JSONDecodeError, KeyError):
                return None
    return None


def make_supervisor_node(model):
    """返回 Supervisor 分诊节点：读 state 决定 route，返回 route + route_history。"""
    tracer = getattr(model, "tracer", None)

    @trace_step(tracer, "node:supervisor")
    def supervisor(state):
        history = state.get("route_history", [])
        unvisited = [n for n in ("lineage", "sql", "cases") if n not in history]
        if not unvisited:
            return {"route": "done"}  # 全派过 → 终止

        findings = {k: state.get(k, []) for k in _SPECIALIST_KEYS.values()}
        route = _llm_route(model, state.get("anomalies", []), findings, unvisited)
        if route not in unvisited:
            route = _fallback_route(unvisited)  # LLM 无效/非法/选了已跑过的 → 兜底

        return {"route": route, "route_history": history + [route]}
    return supervisor

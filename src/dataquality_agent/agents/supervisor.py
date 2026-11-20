"""Supervisor 分诊节点（§13）：一次性给每个异常指派一个专职 Agent。

分诊语义：每个异常只派一个专职 Agent（不是全部跑一遍）。
robust 设计（三道兜底，对应文档 §13「分诊」）：
① LLM 无效/超时 → 确定性映射（orphan/lineage_break/freshness → lineage，其余 → sql）；
② 每个 assignment 只允许 {lineage,sql,cases}（结构化 schema），非法值落兜底；
③ 分诊只做一次（不循环），专职 Agent 各处理分给自己的子集。
"""
import json

from dataquality_agent.observability.tracing import trace_step
from dataquality_agent.prompts import SUBMIT_TRIAGE_SCHEMA, build_triage_prompt

_LINEAGE_TYPES = {"orphan", "lineage_break", "freshness"}


def _default_assignment(anomaly) -> str:
    """确定性兜底：上游类异常 → lineage，其余 → sql（数据取证最通用）。"""
    return "lineage" if anomaly.type in _LINEAGE_TYPES else "sql"


def _llm_triage(model, anomalies) -> list[str]:
    """LLM 分诊：为每个异常指派一个专职 Agent，返回 assignments 列表（与 anomalies 对齐）。"""
    resp = model.chat(
        [{"role": "user", "content": build_triage_prompt(anomalies)}],
        tools=[SUBMIT_TRIAGE_SCHEMA],
        tool_choice={"type": "function", "function": {"name": "submit_triage"}},
    )
    for call in (resp or {}).get("tool_calls", []):
        if call.get("function", {}).get("name") == "submit_triage":
            try:
                return json.loads(call["function"]["arguments"]).get("assignments", [])
            except (json.JSONDecodeError, KeyError):
                return []
    return []


def make_triage_node(model):
    """返回 Supervisor 分诊节点：给每个异常指派专职 Agent，产出 assignments + 空 findings。"""
    tracer = getattr(model, "tracer", None)

    @trace_step(tracer, "node:supervisor")
    def triage(state):
        anomalies = state.get("anomalies", [])
        assignments = _llm_triage(model, anomalies)
        # 对齐 + 兜底：长度不够或非法值 → 确定性映射
        result = []
        for i, a in enumerate(anomalies):
            r = assignments[i] if i < len(assignments) else ""
            result.append(r if r in ("lineage", "sql", "cases") else _default_assignment(a))
        return {"assignments": result, "findings": [""] * len(anomalies)}
    return triage

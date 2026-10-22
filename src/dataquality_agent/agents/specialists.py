"""专职调查 Agent（§13 Phase 1）：把 diagnose 的 4 工具拆成 3 个聚焦 Agent。

- 血缘归因：lineage 工具，追查上游依赖。
- SQL 排查：schema + sql 工具，取证实际数据。
- 案例检索：cases 工具，检索相似历史案例。

每个 Agent 独立 system prompt + 工具集 + max_steps 预算，产出 finding（证据文本）。
Phase 2/3 再由 Supervisor 编排 + diagnose 聚合（findings → Diagnosis）。
"""
import json

from dataquality_agent.agents.diagnose import _run_tool
from dataquality_agent.agents.tooling import build_cases_tools, build_lineage_tools, build_sql_tools
from dataquality_agent.observability.tracing import trace_step
from dataquality_agent.prompts import (
    CASES_SPECIALIST_PROMPT,
    LINEAGE_SPECIALIST_PROMPT,
    SQL_SPECIALIST_PROMPT,
    build_specialist_prompt,
)


def _investigate(anomaly, model, tools, system_prompt, max_steps, tracer) -> str:
    """聚焦工具循环：只调自己的工具收集证据，返回 evidence 文本（finding）。"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": build_specialist_prompt(anomaly)},
    ]
    tool_schemas = [t.to_openai_schema() for t in tools]
    evidence: list[str] = []
    for _ in range(max_steps):
        resp = model.chat(messages, tools=tool_schemas)
        tool_calls = resp.get("tool_calls", [])
        if not tool_calls:
            break
        messages.append({"role": "assistant", "content": "", "tool_calls": tool_calls})
        for call in tool_calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}
            tool = next((t for t in tools if t.name == name), None)
            result = "unknown tool" if tool is None else _run_tool(tool, args, tracer)
            evidence.append(f"{name}({args}) -> {result}")
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result})
    return "\n".join(evidence)


def _make_specialist(name: str, system_prompt: str, model, tools, max_steps: int):
    """通用专职 Agent 工厂：对每个 anomaly 跑聚焦工具循环，产出 findings。"""
    tracer = getattr(model, "tracer", None)

    @trace_step(tracer, f"node:{name}")
    def specialist(state):
        findings = [
            _investigate(a, model, tools, system_prompt, max_steps, tracer)
            for a in state.get("anomalies", [])
        ]
        return {f"{name}_findings": findings}
    return specialist


def make_lineage_agent(model, lineage, max_steps: int = 2):
    """血缘归因专职 Agent：只调 lineage 工具。"""
    return _make_specialist("lineage", LINEAGE_SPECIALIST_PROMPT, model,
                            build_lineage_tools(lineage), max_steps)


def make_sql_agent(model, conn, sql_whitelist=None, max_steps: int = 4):
    """SQL 排查专职 Agent：schema + sql 工具。"""
    return _make_specialist("sql", SQL_SPECIALIST_PROMPT, model,
                            build_sql_tools(conn, sql_whitelist), max_steps)


def make_cases_agent(model, retriever, max_steps: int = 2):
    """案例检索专职 Agent：只调 cases 工具。"""
    tracer = getattr(model, "tracer", None)
    return _make_specialist("cases", CASES_SPECIALIST_PROMPT, model,
                            build_cases_tools(retriever, tracer), max_steps)

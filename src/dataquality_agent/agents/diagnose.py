"""归因 Agent（原生 function calling 工具循环）：查血缘/案例/SQL → 收敛出根因。"""
import json

from dataquality_agent.models import Anomaly, Diagnosis
from dataquality_agent.prompts import SUBMIT_DIAGNOSIS_SCHEMA, build_diagnose_prompt


def _run_tool(tool, args: dict) -> str:
    """执行一个工具调用，异常也返回字符串（不打断循环）。"""
    try:
        return str(tool.func(args))
    except Exception as e:
        return f"tool error: {e}"


def _diagnose_one(anomaly: Anomaly, model, tools: list, max_steps: int) -> Diagnosis:
    messages = [{"role": "user", "content": build_diagnose_prompt(anomaly)}]
    tool_schemas = [t.to_openai_schema() for t in tools] + [SUBMIT_DIAGNOSIS_SCHEMA]
    evidence_chain: list[str] = []

    for _ in range(max_steps):
        resp = model.chat(messages, tools=tool_schemas)
        tool_calls = resp.get("tool_calls", [])
        if not tool_calls:
            break  # 模型既没调工具也没提交结论 → 降级 unknown
        messages.append({"role": "assistant", "content": "", "tool_calls": tool_calls})
        for call in tool_calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}
            if name == "submit_diagnosis":
                try:
                    # evidence_chain 以「实际工具调用历史」为准，不信模型自述
                    return Diagnosis(**args, evidence_chain=evidence_chain)
                except Exception:
                    return Diagnosis(root_cause_category="未知", confidence=0.0, evidence_chain=evidence_chain)
            tool = next((t for t in tools if t.name == name), None)
            result = f"unknown tool: {name}" if tool is None else _run_tool(tool, args)
            evidence_chain.append(f"{name}({args}) -> {result}")
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result})
    # 超过 max_steps 仍不收敛 → 降级 unknown（防无限循环）
    return Diagnosis(root_cause_category="未知", confidence=0.0, evidence_chain=evidence_chain)


def make_diagnose_node(model, tools: list, max_steps: int = 3):
    """返回归因节点函数。model/tools 通过闭包注入（model 需有 .chat；tools 为 Tool 列表）。"""
    def diagnose(state):
        diagnoses = [_diagnose_one(a, model, tools, max_steps) for a in state.get("anomalies", [])]
        return {"diagnoses": diagnoses}
    return diagnose

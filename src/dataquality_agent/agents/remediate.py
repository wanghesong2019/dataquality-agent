"""整改 Agent（Executor + Critic 自评审）：用 function calling 结构化产出修复方案。"""
import json

from dataquality_agent.models import Remediation
from dataquality_agent.prompts import SUBMIT_REMEDIATION_SCHEMA, build_remediate_prompt


def _parse_remediation(resp: dict) -> Remediation:
    """从 assistant message 里取 submit_remediation 工具调用参数；解析/校验失败降级默认值。"""
    for call in resp.get("tool_calls", []):
        if call.get("function", {}).get("name") != "submit_remediation":
            continue
        try:
            args = json.loads(call["function"]["arguments"])
            return Remediation(**args)
        except Exception:
            break  # 参数解析或 Pydantic 校验失败 → 降级
    return Remediation(action_type="ticket", sql_or_suggestion="", risk_level="low")


def make_remediate_node(model):
    """返回整改节点函数。model 通过闭包注入（需有 .chat(messages, tools, tool_choice)）。"""
    def remediate(state):
        remediations = []
        for d in state.get("diagnoses", []):
            resp = model.chat(
                [{"role": "user", "content": build_remediate_prompt(d)}],
                tools=[SUBMIT_REMEDIATION_SCHEMA],
                tool_choice={"type": "function", "function": {"name": "submit_remediation"}},
            )
            remediations.append(_parse_remediation(resp))
        return {"remediations": remediations}
    return remediate

"""归因 Agent（ReAct 工具循环）：查血缘/上游变更/RAG 案例/诊断 SQL → 收敛出根因。"""
import json

from dataquality_agent.models import Anomaly, Diagnosis


def _build_prompt(anomaly: Anomaly, history: list[str]) -> str:
    lines = [
        f"异常：type={anomaly.type}, table={anomaly.table}, column={anomaly.column or '-'}",
    ]
    lines += [f"历史：{h}" for h in history]
    # TODO(M3/M4)：结构化输出增强——改用 Pydantic→JSON Schema 强制（with_structured_output / function calling），
    # 替换下面 prompt 里手写的 JSON schema。手写 schema 依赖模型"猜对"字段名，猜错会静默 fallback 成 unknown。
    lines.append(
        "可用工具：lineage / cases / sql。用 TOOL:<name>:<arg> 调用工具，或输出 JSON 给出根因；"
        'JSON 字段必须为：{"root_cause_category": "字符串", "confidence": 0到1的浮点数}'
    )
    return "\n".join(lines)


def _diagnose_one(anomaly: Anomaly, model, tools: dict, max_steps: int) -> Diagnosis:
    history: list[str] = []
    for _ in range(max_steps):
        resp = model(_build_prompt(anomaly, history)).strip()
        if resp.startswith("TOOL:"):
            _, tool_name, arg = resp.split(":", 2)
            result = tools[tool_name](arg)
            history.append(f"{tool_name}({arg}) -> {result}")
        else:
            try:
                data = json.loads(resp)
            except json.JSONDecodeError:
                data = {}
            return Diagnosis(
                root_cause_category=data.get("root_cause_category", "unknown"),
                confidence=data.get("confidence", 0.0),
                evidence_chain=history,
            )
    # 超过 max_steps 仍不收敛 → 降级 unknown（防无限循环）
    return Diagnosis(root_cause_category="unknown", confidence=0.0, evidence_chain=history)


def make_diagnose_node(model, tools: dict, max_steps: int = 3):
    """返回归因节点函数。model/tools 通过闭包注入（可测试、可替换）。"""
    def diagnose(state):
        diagnoses = [_diagnose_one(a, model, tools, max_steps) for a in state.get("anomalies", [])]
        return {"diagnoses": diagnoses}
    return diagnose

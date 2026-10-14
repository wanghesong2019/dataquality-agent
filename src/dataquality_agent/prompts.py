"""集中管理各 agent 的 prompt 模板与结构化输出 schema（function calling）。"""
from dataquality_agent.models import Remediation


def build_remediate_prompt(diagnosis) -> str:
    """整改 prompt：给根因 → 调 submit_remediation 提交方案。"""
    return (
        f"根因：{diagnosis.root_cause_category}（置信度 {diagnosis.confidence}）。"
        "请调用 submit_remediation 提交修复方案。"
        "risk_level 判定：涉及 DELETE/UPDATE 生产表、金额字段、权限变更 → high；"
        "只读建议 → low；其余 → medium。"
    )


# Pydantic → JSON Schema，作为 function calling 的「强制结构化输出」。
# 用 tool_choice 强制模型只返回这个工具调用，参数即对应 Pydantic 模型。
SUBMIT_REMEDIATION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_remediation",
        "description": "提交一条数据质量整改方案",
        "parameters": Remediation.model_json_schema(),
    },
}

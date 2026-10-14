"""集中管理各 agent 的 prompt 模板与结构化输出 schema（function calling）。"""
from dataclasses import dataclass
from typing import Callable

from dataquality_agent.models import Diagnosis, Remediation


@dataclass
class Tool:
    """一个可被 function calling 调用的工具：schema + 执行函数。"""

    name: str
    description: str
    parameters: dict
    func: Callable  # func(args: dict) -> str

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


# ---- 整改（remediate）----

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


# ---- 归因（diagnose）----

def build_diagnose_prompt(anomaly) -> str:
    """归因 prompt：给异常 → 调工具调查根因 → 调 submit_diagnosis 提交结论。"""
    return (
        f"异常：type={anomaly.type}, table={anomaly.table}, column={anomaly.column or '-'}。"
        "可调用工具调查根因（lineage 查血缘 / cases 查相似案例 / sql 跑只读诊断），"
        "最后调用 submit_diagnosis 提交结论。根因结论必须基于工具证据。"
    )


SUBMIT_DIAGNOSIS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_diagnosis",
        "description": "提交一条异常归因结论",
        "parameters": Diagnosis.model_json_schema(),
    },
}

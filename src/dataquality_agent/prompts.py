"""集中管理各 agent 的 prompt 模板与结构化输出 schema（function calling）。"""
from dataclasses import dataclass
from typing import Callable

from dataquality_agent.models import CriticVerdict, Diagnosis, Remediation


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

def build_remediate_prompt(anomaly, diagnosis) -> str:
    """整改 prompt：给异常 + 根因 → 调 submit_remediation 提交方案。"""
    return (
        f"异常：type={anomaly.type}, table={anomaly.table}, column={anomaly.column or '-'}。"
        f"根因：{diagnosis.root_cause_category}（置信度 {diagnosis.confidence}）。"
        "请调用 submit_remediation 提交修复方案。"
        "action_type 与风险无关：只要能用 SQL 修复（去重、修正负值、回填空值等），"
        "就用 fix_sql 并给出纯 SQL（不要 -- 注释、不要解释文字、不要 ``` 代码块，只要能直接执行的 SQL 语句，表名/列名用上面给到的）；"
        "对真值已丢失的脏数据（负价格、空值），用 best-effort 修复即可（如 price=ABS(price) 或置 0/NULL），不要因真值不可知就改开 ticket；"
        "只有确实无法用 SQL 修复（上游任务需重跑、需人工判断）才用 ticket。"
        "risk_level 单独判定：涉及 DELETE/UPDATE 生产表、金额字段、权限变更 → high（高危只影响是否审批，仍要给 fix_sql）；"
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


def build_critic_prompt(anomaly, diagnosis, candidate: Remediation) -> str:
    """Critic prompt：给异常 + 根因 + 候选方案 → 调 submit_critique 评审（只判语义，硬错误规则闸门已查）。"""
    return (
        f"异常：type={anomaly.type}, table={anomaly.table}, column={anomaly.column or '-'}。"
        f"根因：{diagnosis.root_cause_category}（置信度 {diagnosis.confidence}）。"
        f"候选方案：action_type={candidate.action_type}, risk_level={candidate.risk_level}, "
        f"sql_or_suggestion={candidate.sql_or_suggestion}。"
        "请调用 submit_critique 评审。重点：① action_type 归类是否对（该 fix_sql 却开 ticket / 反之）；"
        "② sql_or_suggestion 能否消除该异常（对真值已丢失的脏数据如负价格/空值，best-effort 修复如 ABS/置默认值即可，"
        "不要求恢复不可知的真值；只查 SQL 是否可执行、列名/表名是否存在、是否真能消除异常且不引入新错误）；"
        "③ risk_level 判得准不准（金额字段、权限变更、生产表写操作应判 high）。"
    )


SUBMIT_CRITIQUE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_critique",
        "description": "提交一条整改方案的评审结论",
        "parameters": CriticVerdict.model_json_schema(),
    },
}


# ---- 归因（diagnose）----

DIAGNOSE_SYSTEM_PROMPT = (
    "你是数据质量根因分析专家。调查异常根因必须分两步："
    "① 先调用工具收集证据——schema 查表的列名与类型、lineage 查上游血缘、cases 查相似案例、sql 跑只读诊断"
    "（写 SQL 前务必先调 schema 确认列名，不要猜列名）；"
    "② 基于证据再调用 submit_diagnosis 提交根因结论。"
    "严禁跳过工具调查、在没有证据时提交「未知」或占位结论。"
)


def build_diagnose_prompt(anomaly) -> str:
    """归因 prompt：给异常 → 先调工具调查根因 → 再调 submit_diagnosis 提交结论。"""
    return (
        f"异常：type={anomaly.type}, table={anomaly.table}, column={anomaly.column or '-'}。"
        "请先调用工具（lineage/cases/sql）收集证据，再调用 submit_diagnosis 提交结论。"
    )


SUBMIT_DIAGNOSIS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_diagnosis",
        "description": "提交一条异常归因结论",
        "parameters": Diagnosis.model_json_schema(),
    },
}


# ---- 报告（report）----

def build_report_prompt(anomaly_count: int, remediation_count: int) -> str:
    """报告 prompt：给汇总数字 → 生成一句总结。"""
    return f"汇总：{anomaly_count} 个异常，{remediation_count} 个整改方案"

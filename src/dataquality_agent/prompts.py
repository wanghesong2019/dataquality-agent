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
    """整改 prompt：给异常 + 根因 + 诊断证据链 → 调 submit_remediation 提交方案。

    关键：把诊断阶段的 evidence_chain（含真实 schema 与查询结果）一并给整改，让它"看到"真实数据、
    按真实列名写 SQL，而不是凭 type/table 盲猜（盲猜导致臆造列名或过度开 ticket）。
    """
    evidence = "\n".join(diagnosis.evidence_chain) if diagnosis.evidence_chain else "（无）"
    return (
        f"异常：type={anomaly.type}, table={anomaly.table}, column={anomaly.column or '-'}。"
        f"根因：{diagnosis.root_cause_category}（置信度 {diagnosis.confidence}）。"
        f"诊断阶段收集的证据（含真实 schema 与查询结果，写 SQL 必须以这些列名/数据为准，不要臆造列名）：\n{evidence}\n"
        "请调用 submit_remediation 提交修复方案。action_type 看异常类型、不看风险："
        "① 值错了但可合理修正（duplicate 去重、value_range 负价格改成 ABS(price) 或 0）→ fix_sql，best-effort 即可，不要因真值不可知就开 ticket；"
        "② 真值已丢失、SQL 无法无损恢复（orphan 上游删数据、null_rate 关键列被置空）→ ticket（需上游重跑/人工判断），不要用硬删/硬填糊弄；"
        "fix_sql 给纯 SQL（不要 -- 注释、不要解释文字、不要 ``` 代码块，只要能直接执行的 SQL 语句，表名/列名用证据链里的真实列名；数据库是 DuckDB，去重/行定位用 rowid，不是 ctid）。"
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
    "根因归类参考：负值/重复键/必填列空值 → 脏数据注入；"
    "子表外键在父表找不到（孤儿）→ 上游任务失败（上游删数据/未加载）；"
    "下游表停更或水位线落后 → 上游数据延迟；"
    "列被删/改类型 → schema变更。"
    "严禁跳过工具调查、在没有证据时提交「未知」或占位结论。"
)


def build_diagnose_prompt(anomaly) -> str:
    """归因 prompt：给异常 → 先调工具调查根因 → 再调 submit_diagnosis 提交结论。"""
    return (
        f"异常：type={anomaly.type}, table={anomaly.table}, column={anomaly.column or '-'}。"
        "请先调用工具（lineage/cases/sql）收集证据，再调用 submit_diagnosis 提交结论。"
    )


def build_aggregate_diagnose_prompt(anomaly, evidence: list[str]) -> str:
    """聚合诊断 prompt（§13 Supervisor 的 diagnose 聚合节点）：给异常 + 专职 Agent 已收集的证据
    → 调 submit_diagnosis 提交结论（证据已收集，不再调工具）。"""
    evidence_text = "\n".join(evidence) if evidence else "（无）"
    return (
        f"异常：type={anomaly.type}, table={anomaly.table}, column={anomaly.column or '-'}。"
        f"专职 Agent 已收集的证据：\n{evidence_text}\n"
        "根因归类参考：负值/重复键/必填列空值 → 脏数据注入；子表外键在父表找不到（孤儿）→ 上游任务失败；"
        "下游表停更或水位线落后 → 上游数据延迟；列被删/改类型 → schema变更。"
        "请调用 submit_diagnosis 提交根因结论。"
    )


SUBMIT_DIAGNOSIS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_diagnosis",
        "description": "提交一条异常归因结论",
        "parameters": Diagnosis.model_json_schema(),
    },
}


# ---- 专职调查 Agent（§13 Supervisor 的 3 个 specialist）----

LINEAGE_SPECIALIST_PROMPT = (
    "你是血缘归因专家。调 lineage 工具查异常表的上游血缘，回答「这张表的数据依赖哪些上游表」。"
    "只做血缘追查，不跑 SQL、不检索案例。"
)

SQL_SPECIALIST_PROMPT = (
    "你是 SQL 排查专家。先调 schema 确认列名与类型（不要猜列名），再调 sql 跑只读诊断查询，"
    "取证异常的实际数据（有多少行、具体哪些值）。只做 SQL 取证，不查血缘、不检索案例。"
)

CASES_SPECIALIST_PROMPT = (
    "你是案例检索专家。调 cases 工具在历史案例库检索与当前异常最相似的案例。"
    "只做案例检索，不跑 SQL、不查血缘。"
)


def build_specialist_prompt(anomaly) -> str:
    """专职 Agent 的 user prompt：给异常 → 调工具收集证据。"""
    return (
        f"异常：type={anomaly.type}, table={anomaly.table}, column={anomaly.column or '-'}。"
        "请调用工具收集证据。"
    )


# ---- Supervisor 分诊（§13）----

SUBMIT_TRIAGE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_triage",
        "description": "为每个异常指派一个专职 Agent",
        "parameters": {
            "type": "object",
            "properties": {
                "assignments": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["lineage", "sql", "cases"]},
                },
            },
            "required": ["assignments"],
        },
    },
}


def build_triage_prompt(anomalies) -> str:
    """Supervisor 分诊 prompt：给异常清单，为每个异常指派一个专职 Agent。"""
    desc = "; ".join(f"[{i}] {a.type}/{a.table}" for i, a in enumerate(anomalies))
    return (
        f"异常清单（按顺序）：{desc}。"
        "为每个异常指派一个专职 Agent（lineage=血缘归因、sql=SQL排查、cases=案例检索）。"
        "规则：孤儿外键/停更/血缘断裂 → lineage；重复/负值/空值/一致性 → sql；不确定可查案例 → cases。"
        "调用 submit_triage 返回 assignments 列表（与异常一一对应）。"
    )


# ---- 报告（report）----

def build_report_prompt(anomaly_count: int, remediation_count: int) -> str:
    """报告 prompt：给汇总数字 → 生成一句总结。"""
    return f"汇总：{anomaly_count} 个异常，{remediation_count} 个整改方案"

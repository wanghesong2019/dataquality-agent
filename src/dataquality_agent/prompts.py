"""集中管理各 agent 的 prompt 模板与结构化输出 schema（function calling）。"""
from dataclasses import dataclass
from typing import Callable

from dataquality_agent.models import CriticVerdict, Remediation


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
    evidence = "\n".join(diagnosis.evidence_chain) if diagnosis.evidence_chain else "(none)"
    return (
        f"Anomaly: type={anomaly.type}, table={anomaly.table}, column={anomaly.column or '-'}."
        f"Root cause: {diagnosis.root_cause_category} (confidence {diagnosis.confidence})."
        f"Evidence collected during diagnosis (includes real schema and query results; write SQL strictly "
        f"using these column names/data, do not invent columns):\n{evidence}\n"
        "Call submit_remediation to submit the fix. Pick action_type by anomaly type, not risk:"
        "① value wrong but reasonably fixable (duplicate dedup, value_range negative price → ABS(price) or 0) "
        "→ fix_sql, best-effort is fine, do not open a ticket just because the true value is unknown;"
        "② true value lost, SQL cannot losslessly recover (orphan upstream deletion, null_rate key column nulled) "
        "→ ticket (needs upstream rerun / human judgment), do not fudge with hard delete/hard fill;"
        "fix_sql must be pure SQL (no -- comments, no prose, no ``` code fence, only directly executable SQL; "
        "use real table/column names from the evidence chain; DB is DuckDB, use rowid for dedup/row targeting, not ctid)."
        "risk_level judged separately: DELETE/UPDATE on production table, monetary fields, permission change → high "
        "(high only affects whether approval is needed, still give fix_sql);"
        "read-only suggestion → low; otherwise → medium."
    )


# Pydantic → JSON Schema，作为 function calling 的「强制结构化输出」。
# 用 tool_choice 强制模型只返回这个工具调用，参数即对应 Pydantic 模型。
SUBMIT_REMEDIATION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_remediation",
        "description": "Submit a data quality remediation plan",
        # 只让模型输出「它决定的字段」；evidence 由代码侧从根因证据装配（判断皆有据），
        # 塞进 schema 会让模型复述整包证据、撑爆 completion token。
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {"type": "string", "description": "Fix action type: fix_sql (fix SQL) / add_rule (add quality rule) / ticket (create ticket) / alert (alert notification)"},
                "sql_or_suggestion": {"type": "string", "description": "Fix SQL or suggestion text"},
                "risk_level": {"type": "string", "description": "Risk level low/medium/high; DELETE/UPDATE on production table, monetary fields, permission change → high"},
            },
            "required": ["action_type", "sql_or_suggestion"],
        },
    },
}


def build_critic_prompt(anomaly, diagnosis, candidate: Remediation) -> str:
    """Critic prompt：给异常 + 根因 + 候选方案 → 调 submit_critique 评审（只判语义，硬错误规则闸门已查）。"""
    return (
        f"Anomaly: type={anomaly.type}, table={anomaly.table}, column={anomaly.column or '-'}."
        f"Root cause: {diagnosis.root_cause_category} (confidence {diagnosis.confidence})."
        f"Candidate: action_type={candidate.action_type}, risk_level={candidate.risk_level}, "
        f"sql_or_suggestion={candidate.sql_or_suggestion}."
        "Call submit_critique to review. Focus: ① is action_type correct (should be fix_sql but opened ticket / vice versa);"
        "② can sql_or_suggestion eliminate the anomaly (for dirty data with lost true value like negative price / null, "
        "best-effort fix like ABS / default value is fine,"
        "do not require recovering unknowable true value; only check whether the SQL is executable, whether column/table "
        "names exist, and whether it truly eliminates the anomaly without introducing new errors);"
        "③ is risk_level accurate (monetary fields, permission change, production-table writes should be high)."
    )


SUBMIT_CRITIQUE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_critique",
        "description": "Submit a review verdict for a remediation plan",
        "parameters": CriticVerdict.model_json_schema(),
    },
}


# ---- 归因（diagnose）----

DIAGNOSE_SYSTEM_PROMPT = (
    "You are a data quality root-cause analysis expert. Investigating an anomaly's root cause must go in two steps:"
    "① first call tools to collect evidence — schema for a table's column names and types, lineage for upstream "
    "lineage, cases for similar cases, sql for read-only diagnostic queries"
    "(always call schema to confirm column names before writing SQL, do not guess column names);"
    "② then, based on the evidence, call submit_diagnosis to submit the root cause conclusion."
    "Root cause categorization reference: negative values / duplicate keys / nulled required columns → "
    "dirty data injection;"
    "child table foreign key missing from parent (orphan) → upstream task failure (upstream deleted / not loaded);"
    "downstream table stale or watermark lagging → upstream data delay;"
    "column dropped / type changed → schema change."
    "Never skip tool investigation or submit 'unknown' / placeholder conclusions without evidence."
)


def build_diagnose_prompt(anomaly) -> str:
    """归因 prompt：给异常 → 先调工具调查根因 → 再调 submit_diagnosis 提交结论。"""
    return (
        f"Anomaly: type={anomaly.type}, table={anomaly.table}, column={anomaly.column or '-'}."
        "First call tools (lineage/cases/sql) to collect evidence, then call submit_diagnosis to submit the conclusion."
    )


def build_aggregate_diagnose_prompt(anomaly, evidence: list[str]) -> str:
    """诊断 prompt（薄归因 / 聚合诊断共用）：给异常 + 已装配的证据包
    → 调 submit_diagnosis 提交结论（证据已收集，不再调工具）。"""
    evidence_text = "\n".join(evidence) if evidence else "(none)"
    return (
        f"Anomaly: type={anomaly.type}, table={anomaly.table}, column={anomaly.column or '-'}."
        f"Evidence package:\n{evidence_text}\n"
        "Root cause categorization reference: negative values / duplicate keys / nulled required columns → "
        "dirty data injection; child table foreign key missing from parent (orphan) → upstream task failure;"
        "downstream table stale or watermark lagging → upstream data delay; column dropped / type changed → schema change."
        "Call submit_diagnosis to submit the root cause conclusion."
    )


SUBMIT_DIAGNOSIS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_diagnosis",
        "description": "Submit an anomaly root-cause conclusion",
        # 只让模型输出「它决定的字段」；evidence_chain/evidence/matched_cases 由代码侧从真实证据装配，
        # 塞进 schema 会让模型复述整包证据、撑爆 completion token（实测 thin 诊断 ~3.3 万 token/call）。
        "parameters": {
            "type": "object",
            "properties": {
                "root_cause_category": {"type": "string", "description": "Root cause category, must be one of: upstream task failure / upstream data delay / ETL logic change / schema change / real business fluctuation (non-anomaly) / data skew / dirty data injection / unknown"},
                "confidence": {"type": "number", "description": "Confidence in the root cause judgment 0~1"},
            },
            "required": ["root_cause_category", "confidence"],
        },
    },
}


# ---- 专职调查 Agent（§13 Supervisor 的 3 个 specialist）----

LINEAGE_SPECIALIST_PROMPT = (
    "You are a lineage attribution expert. Call the lineage tool to query the anomaly table's upstream lineage and "
    "answer 'which upstream tables does this table's data depend on'."
    "Only trace lineage; do not run SQL, do not retrieve cases."
)

SQL_SPECIALIST_PROMPT = (
    "You are a SQL investigation expert. First call schema to confirm column names and types (do not guess column "
    "names), then call sql to run read-only diagnostic queries,"
    "collecting the anomaly's actual data (how many rows, which specific values). Only do SQL forensics; do not query "
    "lineage, do not retrieve cases."
)

CASES_SPECIALIST_PROMPT = (
    "You are a case retrieval expert. Call the cases tool to retrieve the most similar cases from the historical case "
    "store for the current anomaly."
    "Only retrieve cases; do not run SQL, do not query lineage."
)


def build_specialist_prompt(anomaly) -> str:
    """专职 Agent 的 user prompt：给异常 → 调工具收集证据。"""
    return (
        f"Anomaly: type={anomaly.type}, table={anomaly.table}, column={anomaly.column or '-'}."
        "Call tools to collect evidence."
    )


# ---- Supervisor 分诊（§13）----
# assignments 是模型需输出的核心字段：必须是 array，元素必须来自 enum ["lineage", "sql", "cases"]
# （受控解码保证非法值不出现在输出里）；required 是 JSON Schema 的强制校验，逼模型必须产出 assignments。
SUBMIT_TRIAGE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_triage",
        "description": "Assign a specialist agent to each anomaly",
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
        f"Anomaly list (in order): {desc}."
        "Assign a specialist agent to each anomaly (lineage=lineage attribution, sql=SQL investigation, cases=case retrieval)."
        "Rule: orphan FK / stale / lineage break → lineage; duplicate / negative / null / consistency → sql; uncertain → cases."
        "Call submit_triage to return the assignments list (one-to-one with anomalies)."
    )


# ---- 报告（report）----

def build_report_prompt(anomaly_count: int, remediation_count: int) -> str:
    """报告 prompt：给汇总数字 → 生成一句总结。"""
    return f"Summary: {anomaly_count} anomalies, {remediation_count} remediation plans"

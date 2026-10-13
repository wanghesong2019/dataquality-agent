"""Pydantic 结构化数据模型（检测/归因/整改/报告的公共契约）。"""
from typing import TypedDict

from pydantic import BaseModel, Field


class Anomaly(BaseModel):
    """一条检测出的异常。"""

    type: str  # duplicate / orphan / value_range / null_rate / ...
    table: str
    column: str | None = None
    severity: str = "medium"  # low / medium / high
    evidence: str = ""  # 证据（SQL 结果摘要等）
    metric_value: float | str | None = None
    expected_range: str | None = None


class Diagnosis(BaseModel):
    """归因 Agent 的产出：根因 + 置信度 + 证据链。"""

    root_cause_category: str  # 可枚举：上游任务失败 / 上游数据延迟 / schema 变更 / 业务真实波动 / ...
    confidence: float = Field(ge=0, le=1)  # 0~1
    evidence_chain: list[str] = Field(default_factory=list)  # 证据链（防幻觉：无证据 = 证据不足）
    matched_cases: list[str] = Field(default_factory=list)  # RAG 检索到的相似案例
    anomaly_id: str | None = None


class Remediation(BaseModel):
    """整改 Agent 的产出：修复方案 + 风险等级。"""

    action_type: str  # fix_sql / add_rule / ticket / alert
    sql_or_suggestion: str
    risk_level: str = "low"  # low / medium / high
    anomaly_id: str | None = None

    @property
    def requires_approval(self) -> bool:
        """高危必须人工审批（从 risk_level 派生，单一真相源，避免两字段不一致）。"""
        return self.risk_level == "high"


class Approval(BaseModel):
    """HITL 审批记录。"""

    remediation_id: str | None = None
    decision: str = "pending"  # pending / approved / rejected


class Report(BaseModel):
    """报告 Agent 的产出：巡检汇总。"""

    run_id: str | None = None
    summary: str = ""
    anomaly_count: int = 0
    remediation_count: int = 0
    total_cost: float = 0.0


class CostLedger(BaseModel):
    """成本台账：Token 数 / 成本 / LLM 调用次数。"""

    total_tokens: int = 0
    total_cost: float = 0.0
    llm_calls: int = 0


class AgentState(TypedDict, total=False):
    """LangGraph 共享状态（多 Agent 间通过它通信）。"""

    run_id: str
    target: dict
    anomalies: list[Anomaly]
    diagnoses: list[Diagnosis]
    remediations: list[Remediation]
    approvals: list[Approval]
    report: Report | None
    loop_count: int  # 防循环计数器
    cost: CostLedger  # 成本台账

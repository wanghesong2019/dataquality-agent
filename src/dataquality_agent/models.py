"""Pydantic 结构化数据模型（检测/归因/整改/报告的公共契约）。"""
from typing import TypedDict

from pydantic import BaseModel, Field, field_validator


class Evidence(BaseModel):
    """结构化证据：支撑判定结论的 SQL + 命中行样本 + 期望 vs 实际 + 血缘/影响面。

    「判断皆有据」的落点——任何有结论的地方都携带它；rows 封顶（默认 LIMIT 20，token-cheap），
    lineage/blast_radius 归因时补。
    """

    query: str = ""                  # 触发判定的 SQL（默认空：空证据 / 垫片 / 测试构造）
    rows: list[dict] | None = None    # 命中行样本（截断）
    expected: str | None = None       # 期望（阈值 / 基线 / 规则）
    actual: str | None = None         # 实际观测（count / rate / value）
    lineage: list[str] | None = None      # 上游血缘（归因时补）
    blast_radius: list[str] | None = None # 下游影响面（归因时补）


class Anomaly(BaseModel):
    """一条检测出的异常。"""

    type: str  # duplicate / orphan / value_range / null_rate / ...
    table: str
    column: str | None = None
    severity: str = "medium"  # low / medium / high
    evidence: Evidence = Field(default_factory=Evidence)  # 结构化证据（一等公民，不再是自由文本）
    metric_value: float | str | None = None
    expected_range: str | None = None

    @field_validator("evidence", mode="before")
    @classmethod
    def _coerce_legacy_evidence(cls, v):
        """迁移垫片：旧的 str 证据自动包成 Evidence(actual=...)。

        L0/L1 规则迁完后此分支不再触发；L2 semantic.py（v0.2 范围外）仍产 str，由它兜住。
        """
        if isinstance(v, str):
            return Evidence(query="", actual=v)
        return v

    @property
    def summary(self) -> str:
        """回吐旧文本（human-readable 摘要），兼容现有消费方（如 CLI 打印）。"""
        return self.evidence.actual or ""


class Diagnosis(BaseModel):
    """归因 Agent 的产出：根因 + 置信度 + 证据链。"""

    root_cause_category: str = Field(description="根因类别，必须从以下枚举选一：上游任务失败 / 上游数据延迟 / ETL逻辑变更 / schema变更 / 业务真实波动(非异常) / 数据倾斜 / 脏数据注入 / 未知")
    confidence: float = Field(ge=0, le=1, description="对根因判断的置信度 0~1")
    evidence_chain: list[str] = Field(default_factory=list, description="证据链（调用的工具及结果，防幻觉）")
    evidence: list[Evidence] = Field(default_factory=list, description="支撑根因的结构化证据（一等公民）")
    matched_cases: list[str] = Field(default_factory=list, description="RAG 检索到的相似案例 ID")
    anomaly_id: str | None = Field(default=None, description="对应的异常 ID")


class Remediation(BaseModel):
    """整改 Agent 的产出：修复方案 + 风险等级。"""

    action_type: str = Field(description="修复动作类型：fix_sql(修复SQL) / add_rule(新增质量规则) / ticket(生成工单) / alert(告警通知)")
    sql_or_suggestion: str = Field(description="修复 SQL 或建议文本")
    risk_level: str = Field(default="low", description="风险等级 low/medium/high；涉及 DELETE/UPDATE 生产表、金额字段、权限变更 → high")
    evidence: Evidence | None = Field(default=None, description="提案所依据的根因证据")
    anomaly_id: str | None = Field(default=None, description="对应的异常 ID")

    @property
    def requires_approval(self) -> bool:
        """高危必须人工审批（从 risk_level 派生，单一真相源，避免两字段不一致）。"""
        return self.risk_level == "high"


class CriticVerdict(BaseModel):
    """整改 Critic 的评审结论：passed 是否通过 + feedback 喂回 Executor 重写。"""

    passed: bool = Field(description="这条整改方案是否通过评审")
    feedback: str = Field(default="", description="不通过时的具体批评与修改建议")


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
    # §13 Supervisor 状态
    assignments: list[str]     # 每个异常指派的专职 Agent（lineage/sql/cases）
    findings: list[str]        # 每个异常的 finding（由被指派的专职 Agent 产出，与 anomalies 对齐）

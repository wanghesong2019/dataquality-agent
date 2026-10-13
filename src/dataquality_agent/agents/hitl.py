"""HITL 审批节点：高危整改用 LangGraph interrupt 暂停，等人工 approve/reject。"""
from langgraph.types import interrupt

from dataquality_agent.models import Approval, Remediation


def needs_approval(remediations: list[Remediation]) -> bool:
    """是否存在需要人工审批的高危整改。"""
    return any(r.requires_approval for r in remediations)


def make_approve_node():
    """返回审批节点函数。高危整改时 interrupt 暂停，恢复后记录审批结果。"""
    def approve(state):
        pending = [r for r in state.get("remediations", []) if r.requires_approval]
        if not pending:
            return {"approvals": []}
        # 暂停，把待审批方案交给外部；人工恢复时 interrupt 返回决策
        decision = interrupt({"pending": [r.model_dump() for r in pending]})
        approvals = []
        for i in range(len(pending)):
            d = decision.get(str(i)) if isinstance(decision, dict) else None
            approvals.append(Approval(remediation_id=str(i), decision=d or "pending"))
        return {"approvals": approvals}
    return approve

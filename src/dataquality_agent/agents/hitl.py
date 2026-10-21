"""HITL 审批节点：高危整改用 LangGraph interrupt 暂停，等人工 approve/reject。

核心机制：interrupt 的「两个方向 + 两个时刻」
--------------------------------------------
`decision = interrupt({"pending": [...]})` 这一个调用，衔接了相反的两个方向：

- 参数 `{"pending": [...]}` 是「节点 → 调用者」：暂停那一刻把待审批清单"吐"给
  `graph.invoke` 的调用者（人/前端）。所以要先 `r.model_dump()` 转成普通 dict——载荷要
  离开节点、交给外部、还会被 checkpointer 持久化，不能直接传 Pydantic 对象。
- 返回值 `decision` 是「调用者 → 节点」：恢复那一刻，调用者 `Command(resume=X)` 里的
  `X` 原样变成 `interrupt(...)` 的返回值。

时间线：invoke → 图跑到 interrupt 暂停并返回 → 人读 pending 做决定 →
再次 `graph.invoke(Command(resume={"0": "approved"}), config)` → 图从暂停点继续，
`decision` 拿到 resume 值 → 继续跑完。

两个必须满足的前提（否则 resume 不了）：
1. `build_graph(..., checkpointer=...)` 要传 checkpointer（demo 用 MemorySaver）——
   暂停时 state 靠它持久化，恢复时从它读回来。
2. 两次 invoke 用同一个 `config["configurable"]["thread_id"]`——告诉 LangGraph 这是
   同一个 run，第二次才知道 resume 的是哪次暂停。

回复格式谁规定：LangGraph 不规定，`Command(resume=X)` 的 `X` 可以是任意对象；是下面
`decision.get(str(i))` 这段代码隐含约定了「dict、key=下标 "0"/"1"、value=approved/rejected」。
正因框架不强制，这里做了防御：非 dict 时降级为 "pending"。
"""
from langgraph.types import interrupt

from dataquality_agent.models import Approval, Remediation
from dataquality_agent.observability.tracing import trace_step


def needs_approval(remediations: list[Remediation]) -> bool:
    """是否存在需要人工审批的高危整改。"""
    return any(r.requires_approval for r in remediations)


def make_approve_node(tracer=None):
    """返回审批节点函数。高危整改时 interrupt 暂停，恢复后记录审批结果。"""
    @trace_step(tracer, "node:approve")
    def approve(state):
        """审批节点：过滤高危方案 → interrupt 暂停等人工 → 把 resume 的 decision 映射成 Approval。
        约定的 resume 格式：{"0": "approved", "1": "rejected"}（下标对应 pending 顺序）。"""
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

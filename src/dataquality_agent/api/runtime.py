"""巡检运行时：触发巡检、查询结果、审批恢复（内存态，demo 用，生产换持久化 store）。"""
import uuid

from langgraph.types import Command


def _serialize(value):
    """把 state 里的 Pydantic 模型递归转成 dict（供 JSON 返回）。"""
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


class PatrolRuntime:
    """持有 LangGraph 图，提供 trigger / query / approve 三个操作。

    - trigger：跑图（巡检→归因→整改→审批→报告），高危时图停在审批节点。
    - approve：resume 图（Command(resume=decision)），interrupt 返回决策。
    """

    def __init__(self, graph):
        self.graph = graph
        self._runs: dict[str, dict] = {}

    def trigger(self, run_id: str | None = None) -> dict:
        run_id = run_id or uuid.uuid4().hex[:8]
        config = {"configurable": {"thread_id": run_id}}
        state = self.graph.invoke({}, config)
        # report 还没产出 → 停在了审批节点（有高危整改待审批）
        status = "awaiting_approval" if state.get("report") is None else "completed"
        self._runs[run_id] = {"status": status, "state": state, "config": config}
        return {"run_id": run_id, "status": status}

    def get(self, run_id: str) -> dict:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"unknown run_id: {run_id}")
        return {"run_id": run_id, "status": run["status"], "state": _serialize(run["state"])}

    def approve(self, run_id: str, decision: dict) -> dict:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"unknown run_id: {run_id}")
        state = self.graph.invoke(Command(resume=decision), run["config"])
        run["state"] = state
        run["status"] = "completed"
        return {"run_id": run_id, "status": "completed", "state": _serialize(state)}

    def list_runs(self) -> list[str]:
        return list(self._runs.keys())

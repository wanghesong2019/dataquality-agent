"""巡检运行时：触发巡检、查询结果、审批恢复；RunStore 持久化 run 元数据（跨进程重启恢复）。"""
import sqlite3
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


class RunStore:
    """持久 run 元数据（run_id -> status），跨进程重启后 list_runs/approve 仍可用。

    只存元数据不存 state——state 由 LangGraph checkpointer（SqliteSaver）持久化；
    这里存「有哪些 run、各自什么状态」，让重启后 list_runs/approve 能定位到 run 并 resume。
    """

    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, status TEXT NOT NULL)")
        self._conn.commit()

    def save(self, run_id: str, status: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO runs (run_id, status) VALUES (?, ?)", (run_id, status))
        self._conn.commit()

    def load(self, run_id: str) -> dict | None:
        row = self._conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return {"status": row[0]} if row else None

    def list_ids(self) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT run_id FROM runs ORDER BY rowid").fetchall()]


class PatrolRuntime:
    """持有 LangGraph 图，提供 trigger / query / approve 三个操作。

    - trigger：跑图（巡检→归因→整改→审批→报告），高危时图停在审批节点。
    - approve：resume 图（Command(resume=decision)），interrupt 返回决策。
    - run_store（可选）：持久 run 元数据；配了之后进程重启 list_runs/approve 仍可用。
    """

    def __init__(self, graph, run_store: RunStore | None = None):
        self.graph = graph
        self._runs: dict[str, dict] = {}  # 内存缓存 state（当前进程 get 用）
        self.run_store = run_store

    def _config(self, run_id: str) -> dict:
        return {"configurable": {"thread_id": run_id}}

    def trigger(self, run_id: str | None = None) -> dict:
        run_id = run_id or uuid.uuid4().hex[:8]
        config = self._config(run_id)
        state = self.graph.invoke({}, config)
        # report 还没产出 → 停在了审批节点（有高危整改待审批）
        status = "awaiting_approval" if state.get("report") is None else "completed"
        self._runs[run_id] = {"status": status, "state": state, "config": config}
        if self.run_store:
            self.run_store.save(run_id, status)
        return {"run_id": run_id, "status": status}

    def get(self, run_id: str) -> dict:
        run = self._runs.get(run_id)
        if run is None:
            # 重启后：从 run_store 判存在，从 checkpointer 取 state
            if self.run_store is None or self.run_store.load(run_id) is None:
                raise KeyError(f"unknown run_id: {run_id}")
            state = self.graph.get_state(self._config(run_id)).values
            status = self.run_store.load(run_id)["status"]
            return {"run_id": run_id, "status": status, "state": _serialize(state)}
        return {"run_id": run_id, "status": run["status"], "state": _serialize(run["state"])}

    def approve(self, run_id: str, decision: dict) -> dict:
        run = self._runs.get(run_id)
        if run is None:
            if self.run_store is None or self.run_store.load(run_id) is None:
                raise KeyError(f"unknown run_id: {run_id}")
            config = self._config(run_id)
        else:
            config = run["config"]
        state = self.graph.invoke(Command(resume=decision), config)
        self._runs[run_id] = {"status": "completed", "state": state, "config": config}
        if self.run_store:
            self.run_store.save(run_id, "completed")
        return {"run_id": run_id, "status": "completed", "state": _serialize(state)}

    def list_runs(self) -> list[str]:
        if self.run_store is not None:
            return self.run_store.list_ids()
        return list(self._runs.keys())

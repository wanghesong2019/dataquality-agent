"""FastAPI 后端：触发巡检 / 查询结果 / 高危审批。"""
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dataquality_agent.api.runtime import PatrolRuntime


class ApprovalRequest(BaseModel):
    decision: dict[str, str]  # {"0": "approved", "1": "rejected"}，下标对应待审批方案顺序


def create_app(runtime: PatrolRuntime, static_dir: str | None = None) -> FastAPI:
    """用注入的 runtime 创建 FastAPI 应用（可测试、可替换）。

    static_dir 不为空时，把该目录（前端 dashboard）静态挂到 /。
    """
    app = FastAPI(title="DataAgent 数据质量巡检")

    @app.post("/patrol")
    def trigger_patrol():
        return runtime.trigger()

    @app.get("/patrols")
    def list_patrols():
        return {"run_ids": runtime.list_runs()}

    @app.get("/patrol/{run_id}")
    def get_patrol(run_id: str):
        try:
            return runtime.get(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown run_id: {run_id}")

    @app.post("/patrol/{run_id}/approve")
    def approve_patrol(run_id: str, req: ApprovalRequest):
        try:
            return runtime.approve(run_id, req.decision)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown run_id: {run_id}")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    if static_dir:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app

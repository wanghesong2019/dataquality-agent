"""启动 FastAPI 后端（uvicorn 托管 + APScheduler 定时巡检）。

用法：cd 项目根 && python3 scripts/run_api.py
前提：.env 里有 DEEPSEEK_API_KEY / EMBEDDING_*；数据在 Settings.data_dir。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dataquality_agent.api.main import create_app
from dataquality_agent.api.scheduler import create_scheduler
from dataquality_agent.api.wiring import build_runtime
from dataquality_agent.config import load_env

load_env(ROOT / ".env")

runtime = build_runtime()
app = create_app(runtime)

if __name__ == "__main__":
    import uvicorn

    # 无人值守：每 60 分钟定时巡检一次（高危进审批队列，低危/报告自动完成）
    scheduler = create_scheduler(runtime, interval_minutes=60)
    scheduler.start()
    uvicorn.run(app, host="0.0.0.0", port=8000)

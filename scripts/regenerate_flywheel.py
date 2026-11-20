"""数据飞轮案例库重新生成：只走注入阶段，不跑检测/归因/整改，不耗 LLM。

用法：cd 项目根 && python3 scripts/regenerate_flywheel.py
作用：在干净数仓副本上用 INJECTION_SPECS 注入异常，产出新格式 flywheel_cases.json
（id 唯一化 + 含 desc/remedy + table/column），供 RAG 检索评测在「回流后」案例库上跑。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dataquality_agent.config import Settings, load_env
from dataquality_agent.data.injector import Injector
from dataquality_agent.data.warehouse import Warehouse, clone_warehouse
from dataquality_agent.rag.cases import make_flywheel_case, persist_flywheel_cases

import run_eval  # 复用 INJECTION_SPECS（单一来源，不复制）


def main() -> None:
    load_env(ROOT / ".env")
    settings = Settings()
    eval_db = str(Path(settings.db_path).with_name("eval.duckdb"))

    # 1) 建干净数仓（幂等）→ 2) clone 出一次性副本 → 3) 注入异常
    Warehouse(settings).build()
    clone_warehouse(settings.db_path, eval_db)
    eval_conn = Injector(Settings(db_path=eval_db)).connect()
    injected = Injector(Settings(db_path=eval_db)).run(eval_conn, run_eval.INJECTION_SPECS).injections

    # 4) 飞轮写入侧：新格式案例（id 唯一化 + desc/remedy + table/column）
    cases = [make_flywheel_case(inj) for inj in injected]
    persist_flywheel_cases(cases)
    print(f"[regenerate] {len(cases)} 条飞轮案例已写入 flywheel_cases.json")
    print("ids:")
    for c in cases:
        print(f"  {c['id']}")


if __name__ == "__main__":
    main()

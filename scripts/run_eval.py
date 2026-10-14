"""跑一次完整评估：建仓 → clone → 注入 → 检测 → 归因 → 整改 → 复检 → EvalReport。

用法：cd 项目根 && python3 scripts/run_eval.py
前提：.env 里有 DEEPSEEK_API_KEY；数据在 Settings.data_dir。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dataquality_agent.agents.diagnose import make_diagnose_node
from dataquality_agent.agents.remediate import make_remediate_node
from dataquality_agent.agents.tooling import build_diagnose_tools
from dataquality_agent.config import Settings
from dataquality_agent.data.injector import Injector
from dataquality_agent.data.lineage import Lineage
from dataquality_agent.data.warehouse import Warehouse, clone_warehouse
from dataquality_agent.detection.runner import run_detection
from dataquality_agent.eval.harness import (
    remediate_and_recheck,
    remediation_success_by_reversibility,
    run_eval,
)
from dataquality_agent.llm import DeepSeekClient, LLMAdapter
from dataquality_agent.rag.embedder import BagOfWordsEmbedder
from dataquality_agent.rag.retriever import Retriever


def load_env(path: Path) -> None:
    """极简 .env loader（KEY=VALUE，不依赖 python-dotenv）。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


# 注入计划：可逆（duplicate/value_range）+ 数据丢失（orphan/null_rate），n 按真实数据量定。
# null_rate 要超 5% 阈值，delivered 约 9.9w 单 → n 需 ~6000。
INJECTION_SPECS = [
    {"type": "duplicate", "table": "orders", "key_cols": ["order_id"], "n": 3},
    {"type": "value_range", "table": "order_items", "column": "price", "key_cols": ["order_id", "order_item_id"], "n": 3},
    {"type": "null_rate", "table": "orders", "column": "order_delivered_customer_date",
     "status_col": "order_status", "status_value": "delivered", "key_cols": ["order_id"], "n": 6000},
    {"type": "orphan", "child_table": "order_items", "parent_table": "orders",
     "parent_pk": "order_id", "child_fk": "order_id", "n": 20},
]

# 历史案例库（喂给 RAG 的 cases 工具）
CASES = [
    {"id": "dup_orders", "text": "orders 表 order_id 主键重复，上游 ETL 去重逻辑失效，根因脏数据注入，整改去重 DELETE"},
    {"id": "neg_price", "text": "order_items 价格出现负值，数据录入错误，根因脏数据注入，整改回填正确价格"},
    {"id": "null_delivery", "text": "delivered 订单交付日期为 null，数据采集缺失，根因脏数据注入，整改回填日期"},
    {"id": "orphan_items", "text": "order_items 出现孤儿外键，上游 orders 行被删，根因上游任务失败，整改重跑上游加载"},
]


def build_retriever() -> Retriever:
    """词袋案例检索器（P2 部署 BGE-M3 后换 OpenAIEmbedder）。"""
    vocab = sorted({w for c in CASES for w in c["text"].split()})
    r = Retriever(BagOfWordsEmbedder(vocab))
    r.index(CASES)
    return r


def main() -> None:
    load_env(ROOT / ".env")
    settings = Settings()
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    eval_db = str(Path(settings.db_path).with_name("eval.duckdb"))

    # 1) 建干净数仓 + 捕获基线（current_date / expected_schema）
    Warehouse(settings).build()
    clean = Injector(settings).connect()
    current_date = str(clean.execute("SELECT MAX(order_purchase_timestamp::DATE) FROM dwd_orders").fetchone()[0])
    expected_schema = {"dwd_orders": {r[0]: r[1] for r in clean.execute("DESCRIBE dwd_orders").fetchall()}}

    # 2) clone 干净数仓 → 一次性 eval DB，注入异常
    clone_warehouse(settings.db_path, eval_db)
    eval_settings = Settings(db_path=eval_db)
    eval_conn = Injector(eval_settings).connect()
    injected = Injector(eval_settings).run(eval_conn, INJECTION_SPECS).injections

    # 3) 检测
    detection_report = run_detection(eval_conn, current_date=current_date, expected_schema=expected_schema)
    detected_before = detection_report.anomalies

    # 4) 归因 + 整改（DeepSeek function calling）
    adapter = LLMAdapter(DeepSeekClient())
    tools = build_diagnose_tools(eval_conn, Lineage(), build_retriever())
    diagnoses = make_diagnose_node(adapter, tools)({"anomalies": detected_before})["diagnoses"]
    remediations = make_remediate_node(adapter)({"diagnoses": diagnoses})["remediations"]

    # 5) 复检（应用 fix_sql → 重跑检测）
    detected_after = remediate_and_recheck(eval_conn, remediations, current_date, expected_schema)

    # 6) 组装报告 + 分型
    report = run_eval(injected, detected_before, diagnoses, detected_after,
                      detection_report.stats, adapter.cost_ledger)
    by_rev = remediation_success_by_reversibility(detected_before, detected_after, injected)

    print("=" * 64)
    print(f"检测 P/R/F1：P={report.detection.precision:.3f} R={report.detection.recall:.3f} F1={report.detection.f1:.3f}")
    print(f"检测按类型（F1）：{ {k: round(v.f1, 3) for k, v in report.detection_by_type.items()} }")
    print(f"归因正确率：{report.attribution_accuracy:.3f}")
    print(f"整改成功率（复检，整体）：{report.remediation_success:.3f}")
    print(f"整改成功率（分型）：{ {k: round(v, 3) for k, v in by_rev.items()} }")
    print(f"端到端成功率：{report.end_to_end_success:.3f}")
    print(f"耗时/成本：latency={report.latency_seconds:.2f}s tokens={report.total_tokens} llm_calls={report.llm_calls}")
    print("=" * 64)


if __name__ == "__main__":
    main()

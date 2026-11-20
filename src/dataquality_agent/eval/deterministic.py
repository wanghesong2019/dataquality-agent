"""无 LLM 确定性评估：自包含建仓 + 注入 + 检测 + F1（dqagent eval / CI F1 门禁共用）。"""
from pathlib import Path

from dataquality_agent.adapters import DuckDBAdapter
from dataquality_agent.config import Settings
from dataquality_agent.data.injector import Injector
from dataquality_agent.data.warehouse import Warehouse, clone_warehouse
from dataquality_agent.detection.runner import run_detection
from dataquality_agent.eval.harness import run_eval
from dataquality_agent.models import CostLedger

# 自包含样本数据（dqagent init 生成的 mini Olist 3 单）的注入计划。
# 全部 L0 可确定性检出，检测 F1 应 == 1.0（CI 硬门禁）。
SAMPLE_INJECTION_SPECS = [
    {"type": "duplicate", "table": "orders", "key_cols": ["order_id"], "n": 1},
    {"type": "orphan", "child_table": "order_items", "parent_table": "products",
     "parent_pk": "product_id", "child_fk": "product_id", "n": 1},
    # 注 products.product_weight_g（负重量）而非 order_items.price：改价格会连带触发
    # amount_mismatch（支付总额≠明细总额），多出非注入的检测 = 误报。
    {"type": "value_range", "table": "products", "column": "product_weight_g",
     "key_cols": ["product_id"], "n": 1, "bad_value": -5.0},
    {"type": "null_rate", "table": "orders", "column": "customer_id",
     "key_cols": ["order_id"], "n": 1},
]


def run_deterministic_eval(settings: Settings, injection_specs=None):
    """跑一次无 LLM 确定性评估：建仓 → clone → 注入 → 检测 → baseline-aware 检测 F1。

    settings 指向你要评估的数仓（data_dir + db_path）；injection_specs 缺省用
    SAMPLE_INJECTION_SPECS（自包含样本），换成自己数仓时传你自己的注入计划。
    """
    specs = injection_specs if injection_specs is not None else SAMPLE_INJECTION_SPECS
    # 1) 建干净数仓 + 捕获基线（current_date / expected_schema / 已知基线异常）
    Warehouse(settings).build()
    clean = Injector(settings).connect()
    current_date = str(clean.execute("SELECT MAX(order_purchase_timestamp::DATE) FROM dwd_orders").fetchone()[0])
    expected_schema = {"dwd_orders": {r[0]: r[1] for r in clean.execute("DESCRIBE dwd_orders").fetchall()}}
    baseline = run_detection(DuckDBAdapter(clean), current_date=current_date,
                             expected_schema=expected_schema).anomalies

    # 2) clone 干净数仓 → 一次性 eval DB，注入异常
    eval_db = str(Path(settings.db_path).with_name("eval.duckdb"))
    clone_warehouse(settings.db_path, eval_db)
    eval_settings = Settings(db_path=eval_db)
    eval_conn = Injector(eval_settings).connect()
    injected = Injector(eval_settings).run(eval_conn, specs).injections

    # 3) 检测 + 无 LLM EvalReport
    report = run_detection(DuckDBAdapter(eval_conn), current_date=current_date,
                           expected_schema=expected_schema)
    return run_eval(injected, report.anomalies, [], [], report.stats, CostLedger(),
                    baseline=baseline, detected_all=report.anomalies, llm=False)

"""跑一次完整评估：建仓 → clone → 注入 → 检测 → 归因 → 整改 → 复检 → EvalReport。

用法：cd 项目根 && python3 scripts/run_eval.py
前提：.env 里有 DEEPSEEK_API_KEY；数据在 Settings.data_dir。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dataquality_agent.agents.diagnose import make_aggregate_diagnose_node
from dataquality_agent.agents.remediate import make_remediate_node
from dataquality_agent.agents.specialists import make_cases_agent, make_lineage_agent, make_sql_agent
from dataquality_agent.agents.supervisor import make_triage_node
from dataquality_agent.config import Settings, load_env
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
from dataquality_agent.observability.tracing import Tracer
from dataquality_agent.rag.cases import build_retriever


# 注入计划：可逆（duplicate/value_range）+ 数据丢失（orphan/null_rate），n 按真实数据量定。
# null_rate 要超 5% 阈值，delivered 约 9.9w 单 → n 需 ~6000。
INJECTION_SPECS = [
    # orphan 删「叶子」父表 products（而非中心表 orders）：删 orders 会同时孤儿 order_items/payments/reviews
    # 三个子表，一次注入被检出成 3 条、与 ground-truth 对不上。删 products 只破坏 order_items→products 一条 FK。
    {"type": "orphan", "child_table": "order_items", "parent_table": "products",
     "parent_pk": "product_id", "child_fk": "product_id", "n": 20},
    {"type": "duplicate", "table": "orders", "key_cols": ["order_id"], "n": 3},
    {"type": "value_range", "table": "order_items", "column": "price", "key_cols": ["order_id", "order_item_id"], "n": 3},
    {"type": "null_rate", "table": "orders", "column": "order_delivered_customer_date",
     "status_col": "order_status", "status_value": "delivered", "key_cols": ["order_id"], "n": 6000},
    # Tier 1 新增：injector 已有方法 + 检测已有，补 L1 端到端 F1 + FK 网覆盖。
    # 注：amount/state/zip 三类是 always-on（真实数据自带，注入 F1 平凡），不注入；
    #     freshness 与 lineage_break 都动水位线、会互相干扰，本轮先注入 lineage_break，freshness 单独测。
    {"type": "orphan", "child_table": "order_items", "parent_table": "sellers",
     "parent_pk": "seller_id", "child_fk": "seller_id", "n": 20},
    {"type": "lineage_break", "table": "daily_metrics", "date_col": "order_date", "n": 2},
    {"type": "schema_drift", "table": "dwd_orders", "drop_column": "order_approved_at"},
    # Tier 2 新增：扩 duplicate/value_range/null 到更多表列（检测规则 + 注入 spec 同步扩）
    {"type": "duplicate", "table": "payments", "key_cols": ["order_id", "payment_sequential"], "n": 3},
    {"type": "duplicate", "table": "reviews", "key_cols": ["review_id"], "n": 3},
    {"type": "value_range", "table": "reviews", "column": "review_score", "key_cols": ["review_id"], "n": 3, "bad_value": 6},
    {"type": "value_range", "table": "payments", "column": "payment_installments", "key_cols": ["order_id", "payment_sequential"], "n": 3, "bad_value": 0},
    {"type": "value_range", "table": "products", "column": "product_weight_g", "key_cols": ["product_id"], "n": 3, "bad_value": -5.0},
    {"type": "null_rate", "table": "orders", "column": "customer_id", "key_cols": ["order_id"], "n": 20},
    # Tier 3 新增：时间倒挂 + 未来日期（新 L0 规则 + 新注入方法）
    {"type": "time_inversion", "n": 3},
    {"type": "future_date", "n": 3},
]


def _supervisor_diagnose(adapter, diagnose_targets, eval_conn, retriever) -> list:
    """Supervisor 版归因：分诊 + 3 专职 Agent（各处理分给自己的子集）+ 聚合。"""
    triage = make_triage_node(adapter)
    lineage_agent = make_lineage_agent(adapter, Lineage())
    sql_agent = make_sql_agent(adapter, eval_conn)
    cases_agent = make_cases_agent(adapter, retriever)
    aggregate = make_aggregate_diagnose_node(adapter)

    state = {"anomalies": diagnose_targets}
    state.update(triage(state))
    state.update(lineage_agent(state))
    state.update(sql_agent(state))
    state.update(cases_agent(state))
    return aggregate(state)["diagnoses"]


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
    # 捕获干净基线：跨表一致性会检出真实数据自带的真问题（如 Olist 380 单支付金额对不上），
    # 这些是「已知基线」而非注入误报，评测时从误报里扣除（baseline-aware eval）。
    baseline = run_detection(clean, current_date=current_date, expected_schema=expected_schema).anomalies

    # 2) clone 干净数仓 → 一次性 eval DB，注入异常
    clone_warehouse(settings.db_path, eval_db)
    eval_settings = Settings(db_path=eval_db)
    eval_conn = Injector(eval_settings).connect()
    injected = Injector(eval_settings).run(eval_conn, INJECTION_SPECS).injections

    # 3) 检测
    detection_report = run_detection(eval_conn, current_date=current_date, expected_schema=expected_schema)
    detected_before = detection_report.anomalies
    # always-on 跨表异常（真实 Olist 自带的 380/609/8556）没有注入 ground-truth，只参与 baseline
    # 扣除、不进归因/整改循环——否则模型会对着它们幻觉出不存在列的 SQL（如 payment_total）。
    inj_keys = {(i.type, i.table) for i in injected}
    diagnose_targets = [a for a in detected_before if (a.type, a.table) in inj_keys]

    # 4) 归因（Supervisor 分诊 + 3 专职 Agent + 聚合）+ 整改（DeepSeek function calling）
    tracer = Tracer()
    adapter = LLMAdapter(DeepSeekClient(temperature=0), tracer=tracer)
    retriever = build_retriever()
    diagnoses = _supervisor_diagnose(adapter, diagnose_targets, eval_conn, retriever)
    remediations = make_remediate_node(adapter, eval_conn)(
        {"anomalies": diagnose_targets, "diagnoses": diagnoses})["remediations"]

    # 5) 复检（应用 fix_sql → 重跑检测）
    detected_after = remediate_and_recheck(eval_conn, remediations, current_date, expected_schema)

    # 6) 组装报告 + 分型
    report = run_eval(injected, diagnose_targets, diagnoses, detected_after,
                      detection_report.stats, adapter.cost_ledger, llm_seconds=tracer.root_duration(),
                      baseline=baseline, detected_all=detected_before)
    by_rev = remediation_success_by_reversibility(diagnose_targets, detected_after, injected)

    print("=" * 64)
    print(f"检测 P/R/F1：P={report.detection.precision:.3f} R={report.detection.recall:.3f} F1={report.detection.f1:.3f}")
    print(f"检测按类型（F1）：{ {k: round(v.f1, 3) for k, v in report.detection_by_type.items()} }")
    print(f"归因正确率：{report.attribution_accuracy:.3f}")
    if report.trajectory:
        t = report.trajectory
        schema_part = f" / sql前查schema {t.schema_before_sql_rate:.0%}" if t.schema_before_sql_rate is not None else ""
        print(f"轨迹质量：合格率 {t.pass_rate:.0%} / 平均 {t.avg_calls:.1f} 次调用 / 冗余 {t.total_redundant} 次{schema_part}")
    print(f"整改成功率（复检，整体）：{report.remediation_success:.3f}")
    print(f"整改成功率（分型）：{ {k: round(v, 3) for k, v in by_rev.items()} }")
    print(f"端到端成功率：{report.end_to_end_success:.3f}")
    if report.failure_taxonomy:
        ft = report.failure_taxonomy
        print(f"失败分型：检测漏 {ft.detection_failure} / 归因错 {ft.attribution_failure} / 整改失败 {ft.remediation_failure} / 成功 {ft.success}（共 {ft.total}）")
    print(f"耗时/成本：latency={report.latency_seconds:.2f}s tokens={report.total_tokens} llm_calls={report.llm_calls}")
    print("=" * 64)


if __name__ == "__main__":
    main()

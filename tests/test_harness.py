import pytest

from dataquality_agent.adapters import DuckDBAdapter
from dataquality_agent.data.injector import Injector, InjectedAnomaly
from dataquality_agent.eval.harness import (
    apply_remediation,
    classify_reversibility,
    remediate_and_recheck,
    remediation_success_by_reversibility,
    run_eval,
)
from dataquality_agent.models import Anomaly, CostLedger, Diagnosis, Remediation


def _inj(type, table, cat):
    return InjectedAnomaly(type=type, table=table, root_cause="x", root_cause_category=cat, location=table)


def test_classify_reversibility():
    assert classify_reversibility("duplicate") == "reversible"
    assert classify_reversibility("value_range") == "reversible"
    assert classify_reversibility("orphan") == "data-loss"
    assert classify_reversibility("null_rate") == "data-loss"
    assert classify_reversibility("lineage_break") == "data-loss"


def test_apply_remediation(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    conn.execute("UPDATE order_items SET price = -5.0 WHERE order_id = 'o1' AND order_item_id = 1")
    r = Remediation(action_type="fix_sql", sql_or_suggestion="UPDATE order_items SET price = 10.0 WHERE order_id = 'o1' AND order_item_id = 1")
    assert apply_remediation(DuckDBAdapter(conn), r) is True
    price = conn.execute("SELECT price FROM order_items WHERE order_id = 'o1' AND order_item_id = 1").fetchone()[0]
    assert price == 10.0


def test_apply_remediation_skips_non_sql_and_invalid(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    assert apply_remediation(DuckDBAdapter(conn), Remediation(action_type="ticket", sql_or_suggestion="请人工处理")) is False
    assert apply_remediation(DuckDBAdapter(conn), Remediation(action_type="fix_sql", sql_or_suggestion="这不是 SQL")) is False


def test_apply_remediation_strips_comment_lines(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    conn.execute("UPDATE order_items SET price = -5.0 WHERE order_id = 'o1' AND order_item_id = 1")
    r = Remediation(action_type="fix_sql", sql_or_suggestion="-- 说明注释\nUPDATE order_items SET price = 10.0 WHERE order_id = 'o1' AND order_item_id = 1")
    assert apply_remediation(DuckDBAdapter(conn), r) is True
    price = conn.execute("SELECT price FROM order_items WHERE order_id = 'o1' AND order_item_id = 1").fetchone()[0]
    assert price == 10.0


def test_apply_remediation_all_comments_returns_false(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    r = Remediation(action_type="fix_sql", sql_or_suggestion="-- 只是说明\n-- 没有实际 SQL")
    assert apply_remediation(DuckDBAdapter(conn), r) is False


def test_remediate_and_recheck(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    inj.run(conn, [{"type": "value_range", "table": "order_items", "column": "price",
                    "key_cols": ["order_id", "order_item_id"]}])
    fix = Remediation(action_type="fix_sql", sql_or_suggestion="UPDATE order_items SET price = 10.0 WHERE price < 0")
    after = remediate_and_recheck(DuckDBAdapter(conn), [fix])
    assert "value_range" not in [a.type for a in after]


def test_remediation_success_by_reversibility():
    injected = [_inj("duplicate", "orders", "脏数据注入"), _inj("orphan", "order_items", "上游任务失败")]
    detected_before = [Anomaly(type="duplicate", table="orders"), Anomaly(type="orphan", table="order_items")]
    detected_after = []
    result = remediation_success_by_reversibility(detected_before, detected_after, injected)
    assert result == {"reversible": 1.0, "data-loss": 1.0}


def test_run_eval_assembles_report():
    injected = [_inj("duplicate", "orders", "脏数据注入")]
    detected = [Anomaly(type="duplicate", table="orders")]
    diagnoses = [Diagnosis(root_cause_category="脏数据注入", confidence=0.9)]
    report = run_eval(injected, detected, diagnoses, [], {"l0_rules": 0.1}, CostLedger(total_tokens=100))
    assert report.detection.precision == 1.0
    assert report.attribution_accuracy == 1.0
    assert report.remediation_success == 1.0
    assert report.end_to_end_success == 1.0
    assert report.total_tokens == 100


def test_run_eval_includes_llm_time():
    injected = [_inj("duplicate", "orders", "脏数据注入")]
    detected = [Anomaly(type="duplicate", table="orders")]
    diagnoses = [Diagnosis(root_cause_category="脏数据注入", confidence=0.9)]
    report = run_eval(injected, detected, diagnoses, [], {"l0_rules": 0.1}, CostLedger(), llm_seconds=5.0)
    assert report.latency_seconds == pytest.approx(5.1)  # 检测 0.1 + LLM 5.0


def test_run_eval_no_llm():
    injected = [_inj("duplicate", "orders", "脏数据注入")]
    detected = [Anomaly(type="duplicate", table="orders")]
    report = run_eval(injected, detected, [], [], {"l0_rules": 0.1}, CostLedger(), llm=False)
    assert report.detection.f1 == 1.0
    assert report.attribution_accuracy is None
    assert report.remediation_success is None
    assert report.end_to_end_success is None

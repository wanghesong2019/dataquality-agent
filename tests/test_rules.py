from dataquality_agent.adapters import DuckDBAdapter
from dataquality_agent.data.injector import Injector
from dataquality_agent.detection.rules import run_consistency_checks, run_rule_checks


def test_clean_warehouse_no_false_positive(mini_warehouse):
    """干净数据（含 canceled 订单的合法 null 交付日期）不该有任何误报。"""
    conn = Injector(mini_warehouse).connect()
    assert run_rule_checks(DuckDBAdapter(conn)) == []


def test_detect_duplicate(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    adapter = DuckDBAdapter(conn)
    inj.run(conn, [{"type": "duplicate", "table": "orders", "key_cols": ["order_id"], "n": 1}])
    assert "duplicate" in [a.type for a in run_rule_checks(adapter)]


def test_detect_orphan(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    adapter = DuckDBAdapter(conn)
    inj.run(conn, [{"type": "orphan", "child_table": "order_items", "parent_table": "orders",
                    "parent_pk": "order_id", "child_fk": "order_id", "n": 1}])
    assert "orphan" in [a.type for a in run_rule_checks(adapter)]


def test_detect_negative_price(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    adapter = DuckDBAdapter(conn)
    conn.execute("UPDATE order_items SET price = -5.0 WHERE order_id = 'o1'")
    assert "value_range" in [a.type for a in run_rule_checks(adapter)]


def test_consistency_checks_clean(mini_warehouse):
    """干净数据不该有跨表一致性误报（金额/状态/邮编/FK 全部一致）。"""
    conn = Injector(mini_warehouse).connect()
    assert run_consistency_checks(DuckDBAdapter(conn)) == []


def test_detect_amount_mismatch(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    adapter = DuckDBAdapter(conn)
    conn.execute("UPDATE payments SET payment_value = 999.0 WHERE order_id = 'o1' AND payment_sequential = 1")
    assert "amount_mismatch" in [a.type for a in run_consistency_checks(adapter)]


def test_detect_state_conflict(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    adapter = DuckDBAdapter(conn)
    conn.execute("INSERT INTO reviews VALUES ('r9', 'o3', 1, '', '', '2018-01-05 00:00:00', '2018-01-06 00:00:00')")
    assert "state_conflict" in [a.type for a in run_consistency_checks(adapter)]


def test_detect_zip_inconsistency(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    adapter = DuckDBAdapter(conn)
    conn.execute("INSERT INTO geolocation VALUES ('01001', -23.6, -46.7, 'campinas', 'SP')")
    assert "zip_inconsistency" in [a.type for a in run_consistency_checks(adapter)]


def test_detect_orphan_fk_product(mini_warehouse):
    conn = Injector(mini_warehouse).connect()
    adapter = DuckDBAdapter(conn)
    conn.execute("DELETE FROM products WHERE product_id = 'p1'")
    assert "orphan" in [a.type for a in run_consistency_checks(adapter)]


def test_null_rate_threshold_controls_detection(mini_warehouse):
    """null_rate_threshold 应真正控制 delivered 交付日期空值检查（不再是死配置）。"""
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    adapter = DuckDBAdapter(conn)
    # 1 个 delivered 订单交付日期置空 → delivered 组 null 率 50%
    inj.run(conn, [{"type": "null_rate", "table": "orders", "column": "order_delivered_customer_date",
                    "status_col": "order_status", "status_value": "delivered",
                    "key_cols": ["order_id"], "n": 1}])
    assert "null_rate" in [a.type for a in run_rule_checks(adapter, null_rate_threshold=0.05)]
    assert "null_rate" not in [a.type for a in run_rule_checks(adapter, null_rate_threshold=0.99)]

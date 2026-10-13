from dataquality_agent.data.injector import Injector
from dataquality_agent.detection.rules import run_rule_checks


def test_clean_warehouse_no_false_positive(mini_warehouse):
    """干净数据（含 canceled 订单的合法 null 交付日期）不该有任何误报。"""
    conn = Injector(mini_warehouse).connect()
    assert run_rule_checks(conn) == []


def test_detect_duplicate(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    inj.run(conn, [{"type": "duplicate", "table": "orders", "key_cols": ["order_id"], "n": 1}])
    assert "duplicate" in [a.type for a in run_rule_checks(conn)]


def test_detect_orphan(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    inj.run(conn, [{"type": "orphan", "child_table": "order_items", "parent_table": "orders",
                    "parent_pk": "order_id", "child_fk": "order_id", "n": 1}])
    assert "orphan" in [a.type for a in run_rule_checks(conn)]


def test_detect_negative_price(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    conn.execute("UPDATE order_items SET price = -5.0 WHERE order_id = 'o1'")
    assert "value_range" in [a.type for a in run_rule_checks(conn)]

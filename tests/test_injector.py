from dataquality_agent.data.injector import Injector


def test_inject_duplicate(mini_warehouse):
    inj = Injector(mini_warehouse)
    gt = inj.run(inj.connect(), [{"type": "duplicate", "table": "orders", "key_cols": ["order_id"], "n": 1}])
    assert len(gt.injections) == 1
    assert gt.injections[0].type == "duplicate"
    assert gt.injections[0].root_cause != ""
    dup = inj.connect().execute(
        "SELECT COUNT(*) FROM (SELECT order_id FROM orders GROUP BY order_id HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    assert dup > 0


def test_inject_orphan(mini_warehouse):
    inj = Injector(mini_warehouse)
    gt = inj.run(inj.connect(), [{"type": "orphan", "child_table": "order_items", "parent_table": "orders",
                                  "parent_pk": "order_id", "child_fk": "order_id", "n": 1}])
    assert gt.injections[0].type == "orphan"
    orphan = inj.connect().execute(
        "SELECT COUNT(*) FROM order_items i LEFT JOIN orders o ON i.order_id = o.order_id WHERE o.order_id IS NULL"
    ).fetchone()[0]
    assert orphan > 0


def test_inject_null_rate(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    gt = inj.run(conn, [{"type": "null_rate", "table": "orders", "column": "order_delivered_customer_date",
                         "status_col": "order_status", "status_value": "delivered", "key_cols": ["order_id"], "n": 1}])
    a = gt.injections[0]
    assert a.type == "null_rate"
    assert a.root_cause_category == "dirty data injection"
    nulls = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE order_status = 'delivered' AND order_delivered_customer_date IS NULL"
    ).fetchone()[0]
    assert nulls >= 1


def test_inject_value_range(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    gt = inj.run(conn, [{"type": "value_range", "table": "order_items", "column": "price",
                         "key_cols": ["order_id", "order_item_id"], "n": 1}])
    a = gt.injections[0]
    assert a.type == "value_range"
    assert a.root_cause_category == "dirty data injection"
    neg = conn.execute("SELECT COUNT(*) FROM order_items WHERE price < 0").fetchone()[0]
    assert neg >= 1


def test_inject_root_cause_category_alignment(mini_warehouse):
    """ground-truth 的 root_cause_category 必须与 Diagnosis 枚举对齐（归因正确率评估的地基）。"""
    inj = Injector(mini_warehouse)
    gt = inj.run(inj.connect(), [
        {"type": "duplicate", "table": "orders", "key_cols": ["order_id"], "n": 1},
        {"type": "orphan", "child_table": "order_items", "parent_table": "orders",
         "parent_pk": "order_id", "child_fk": "order_id", "n": 1},
    ])
    cats = {i.type: i.root_cause_category for i in gt.injections}
    assert cats["duplicate"] == "dirty data injection"
    assert cats["orphan"] == "upstream task failure"


def test_inject_lineage_break(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    before = conn.execute("SELECT MAX(order_date) FROM daily_metrics").fetchone()[0]
    gt = inj.run(conn, [{"type": "lineage_break", "table": "daily_metrics", "date_col": "order_date", "n": 1}])
    a = gt.injections[0]
    assert a.type == "lineage_break"
    assert a.root_cause_category == "upstream data delay"
    after = conn.execute("SELECT MAX(order_date) FROM daily_metrics").fetchone()[0]
    assert after < before  # 删了最近一天 → 下游水位线后退


def test_inject_freshness(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    gt = inj.run(conn, [{"type": "freshness", "table": "daily_metrics", "date_col": "order_date", "n": 1}])
    a = gt.injections[0]
    assert a.type == "freshness"
    assert a.root_cause_category == "upstream data delay"


def test_inject_schema(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    gt = inj.run(conn, [{"type": "schema_drift", "table": "dwd_orders", "drop_column": "order_approved_at"}])
    a = gt.injections[0]
    assert a.type == "schema_drift"
    assert a.root_cause_category == "schema change"
    cols = [r[0] for r in conn.execute("DESCRIBE dwd_orders").fetchall()]
    assert "order_approved_at" not in cols


def test_inject_orphan_orders_customers(mini_warehouse):
    """4.4：孤儿 orders→customers（叶子父表，删 customers 只孤儿 orders、不级联）。"""
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    gt = inj.run(conn, [{"type": "orphan", "child_table": "orders", "parent_table": "customers",
                         "parent_pk": "customer_id", "child_fk": "customer_id", "n": 1}])
    a = gt.injections[0]
    assert a.type == "orphan"
    assert a.table == "orders"
    assert a.root_cause_category == "upstream task failure"
    orphan = conn.execute(
        "SELECT COUNT(*) FROM orders o LEFT JOIN customers c ON o.customer_id = c.customer_id "
        "WHERE c.customer_id IS NULL AND o.customer_id IS NOT NULL"
    ).fetchone()[0]
    assert orphan > 0


def test_inject_time_inversion_second_column(mini_warehouse):
    """4.4：时间倒挂第二列（预估送达日期 < 下单日期）。"""
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    gt = inj.run(conn, [{"type": "time_inversion", "n": 1, "column": "order_estimated_delivery_date"}])
    a = gt.injections[0]
    assert a.type == "time_inversion"
    assert a.column == "order_estimated_delivery_date"
    assert a.root_cause_category == "ETL logic change"
    n = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE order_estimated_delivery_date IS NOT NULL "
        "AND order_estimated_delivery_date < order_purchase_timestamp"
    ).fetchone()[0]
    assert n >= 1


def test_inject_amount_mismatch(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    gt = inj.run(conn, [{"type": "amount_mismatch", "n": 1, "delta": 100.0}])
    a = gt.injections[0]
    assert a.type == "amount_mismatch"
    assert a.root_cause_category == "dirty data injection"
    n = conn.execute("""
        WITH pay AS (SELECT order_id, SUM(payment_value) paid FROM payments GROUP BY order_id),
             item AS (SELECT order_id, SUM(price + freight_value) amount FROM order_items GROUP BY order_id)
        SELECT COUNT(*) FROM pay JOIN item ON pay.order_id = item.order_id WHERE ABS(pay.paid - item.amount) > 0.01
    """).fetchone()[0]
    assert n >= 1


def test_inject_state_conflict(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    gt = inj.run(conn, [{"type": "state_conflict", "n": 1}])
    a = gt.injections[0]
    assert a.type == "state_conflict"
    assert a.root_cause_category == "dirty data injection"
    n = conn.execute("""
        SELECT COUNT(*) FROM orders o JOIN reviews r ON o.order_id = r.order_id WHERE o.order_status = 'canceled'
    """).fetchone()[0]
    assert n >= 1


def test_inject_zip_inconsistency(mini_warehouse):
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    gt = inj.run(conn, [{"type": "zip_inconsistency", "n": 1}])
    a = gt.injections[0]
    assert a.type == "zip_inconsistency"
    assert a.root_cause_category == "dirty data injection"
    n = conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT geolocation_zip_code_prefix FROM geolocation
            GROUP BY geolocation_zip_code_prefix HAVING COUNT(DISTINCT geolocation_city) > 1
        )
    """).fetchone()[0]
    assert n >= 1


def test_inject_join_fanout(mini_warehouse):
    """JOIN 膨胀注入：复制维度表主键行。ground-truth 的 type 对齐检测的 duplicate。"""
    inj = Injector(mini_warehouse)
    conn = inj.connect()
    gt = inj.run(conn, [{"type": "join_fanout", "table": "sellers", "key_cols": ["seller_id"], "n": 1}])
    a = gt.injections[0]
    assert a.type == "duplicate"  # 检测对齐键是 duplicate（维度主键重复是 JOIN 膨胀的根因）
    assert a.root_cause_category == "dirty data injection"
    dup = conn.execute(
        "SELECT COUNT(*) FROM (SELECT seller_id FROM sellers GROUP BY seller_id HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    assert dup > 0

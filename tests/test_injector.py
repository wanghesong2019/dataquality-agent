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
    assert a.root_cause_category == "脏数据注入"
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
    assert a.root_cause_category == "脏数据注入"
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
    assert cats["duplicate"] == "脏数据注入"
    assert cats["orphan"] == "上游任务失败"

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

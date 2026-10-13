import pandas as pd
import pytest

from dataquality_agent.config import Settings
from dataquality_agent.data.injector import Injector
from dataquality_agent.data.warehouse import Warehouse


@pytest.fixture
def mini_warehouse(tmp_path):
    """迷你数仓（与 test_warehouse 相同的迷你数据，后续可抽到 conftest.py 复用）。"""
    orders = pd.DataFrame({
        "order_id": ["o1", "o2", "o3"],
        "customer_id": ["c1", "c2", "c3"],
        "order_status": ["delivered", "delivered", "canceled"],
        "order_purchase_timestamp": ["2018-01-01 10:00:00", "2018-01-01 11:00:00", "2018-01-02 09:00:00"],
        "order_approved_at": ["2018-01-01 10:30:00", "2018-01-01 11:30:00", None],
        "order_delivered_carrier_date": ["2018-01-03 00:00:00", "2018-01-04 00:00:00", None],
        "order_delivered_customer_date": ["2018-01-05 00:00:00", "2018-01-06 00:00:00", None],
        "order_estimated_delivery_date": ["2018-01-08 00:00:00", "2018-01-09 00:00:00", "2018-01-10 00:00:00"],
    })
    items = pd.DataFrame({
        "order_id": ["o1", "o1", "o2"],
        "order_item_id": [1, 2, 1],
        "product_id": ["p1", "p2", "p1"],
        "seller_id": ["s1", "s2", "s1"],
        "shipping_limit_date": ["2018-01-02 00:00:00"] * 3,
        "price": [10.0, 20.0, 5.0],
        "freight_value": [2.0, 3.0, 1.0],
    })
    orders.to_csv(tmp_path / "olist_orders_dataset.csv", index=False)
    items.to_csv(tmp_path / "olist_order_items_dataset.csv", index=False)
    settings = Settings(data_dir=str(tmp_path), db_path=str(tmp_path / "test.duckdb"))
    Warehouse(settings).build()
    return settings


def test_inject_duplicate(mini_warehouse):
    settings = mini_warehouse
    inj = Injector(settings)
    gt = inj.run(
        inj.connect(),
        [{"type": "duplicate", "table": "orders", "key_cols": ["order_id"], "n": 1}],
    )
    assert len(gt.injections) == 1
    assert gt.injections[0].type == "duplicate"
    assert gt.injections[0].root_cause != ""
    dup = inj.connect().execute(
        "SELECT COUNT(*) FROM (SELECT order_id FROM orders GROUP BY order_id HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    assert dup > 0


def test_inject_orphan(mini_warehouse):
    settings = mini_warehouse
    inj = Injector(settings)
    gt = inj.run(
        inj.connect(),
        [{"type": "orphan", "child_table": "order_items", "parent_table": "orders",
          "parent_pk": "order_id", "child_fk": "order_id", "n": 1}],
    )
    assert gt.injections[0].type == "orphan"
    orphan = inj.connect().execute(
        "SELECT COUNT(*) FROM order_items i LEFT JOIN orders o ON i.order_id = o.order_id WHERE o.order_id IS NULL"
    ).fetchone()[0]
    assert orphan > 0

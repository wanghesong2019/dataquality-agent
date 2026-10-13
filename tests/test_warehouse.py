import pandas as pd
import pytest

from dataquality_agent.config import Settings
from dataquality_agent.data.warehouse import Warehouse


@pytest.fixture
def mini_data(tmp_path):
    """迷你 Olist 数据（3 单），让单元测试快且不依赖 100MB 真实数据。"""
    orders = pd.DataFrame({
        "order_id": ["o1", "o2", "o3"],
        "customer_id": ["c1", "c2", "c3"],
        "order_status": ["delivered", "delivered", "canceled"],
        "order_purchase_timestamp": [
            "2018-01-01 10:00:00", "2018-01-01 11:00:00", "2018-01-02 09:00:00",
        ],
        "order_approved_at": [
            "2018-01-01 10:30:00", "2018-01-01 11:30:00", None,
        ],
        "order_delivered_carrier_date": [
            "2018-01-03 00:00:00", "2018-01-04 00:00:00", None,
        ],
        "order_delivered_customer_date": [
            "2018-01-05 00:00:00", "2018-01-06 00:00:00", None,
        ],
        "order_estimated_delivery_date": [
            "2018-01-08 00:00:00", "2018-01-09 00:00:00", "2018-01-10 00:00:00",
        ],
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
    return tmp_path


def test_warehouse_build_and_dws(mini_data):
    s = Settings(data_dir=str(mini_data), db_path=str(mini_data / "test.duckdb"))
    w = Warehouse(s)
    w.build()
    conn = w.connect()
    # ODS 落库
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 3
    # DWS 聚合：2018-01-01 有 o1/o2 两单，gmv = 10+20+5 = 35
    row = conn.execute(
        "SELECT orders, gmv, avg_order_value FROM daily_metrics WHERE order_date = DATE '2018-01-01'"
    ).fetchone()
    assert row[0] == 2
    assert row[1] == 35.0
    assert row[2] == 17.5

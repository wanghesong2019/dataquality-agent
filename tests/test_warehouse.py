from dataquality_agent.config import Settings
from dataquality_agent.data.warehouse import Warehouse


def test_warehouse_build_and_dws(mini_data):
    s = Settings(data_dir=str(mini_data), db_path=str(mini_data / "test.duckdb"))
    w = Warehouse(s)
    w.build()
    conn = w.connect()
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 3
    row = conn.execute(
        "SELECT orders, gmv, avg_order_value FROM daily_metrics WHERE order_date = DATE '2018-01-01'"
    ).fetchone()
    assert row[0] == 2
    assert row[1] == 35.0
    assert row[2] == 17.5

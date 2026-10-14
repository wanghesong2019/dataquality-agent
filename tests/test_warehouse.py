import duckdb
from pathlib import Path

from dataquality_agent.config import Settings
from dataquality_agent.data.warehouse import Warehouse, clone_warehouse


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


def test_clone_warehouse(mini_warehouse):
    dst = str(Path(mini_warehouse.db_path).with_name("clone.duckdb"))
    clone_warehouse(mini_warehouse.db_path, dst)

    src = duckdb.connect(mini_warehouse.db_path)
    clone = duckdb.connect(dst)
    src_tables = sorted(t[0] for t in src.execute("SHOW TABLES").fetchall())
    clone_tables = sorted(t[0] for t in clone.execute("SHOW TABLES").fetchall())
    assert src_tables == clone_tables
    for t in src_tables:
        assert clone.execute(f"SELECT COUNT(*) FROM {t}").fetchone() == src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()

    # 改 clone 不影响原库：eval 在副本上注入，不污染干净数仓
    before = src.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    clone.execute("INSERT INTO orders SELECT * FROM orders LIMIT 1")
    assert src.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == before
    assert clone.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == before + 1

"""WarehouseAdapter + DuckDBAdapter 测试。"""
from dataquality_agent.adapters import DuckDBAdapter


def test_list_tables_and_schema(mini_warehouse):
    adapter = DuckDBAdapter(mini_warehouse.db_path)
    tables = adapter.list_tables()
    assert "dwd_orders" in tables
    assert "daily_metrics" in tables
    schema = adapter.describe_table("dwd_orders")
    assert schema  # 非空 dict
    assert adapter.row_count("dwd_orders") > 0
    adapter.close()


def test_execute_returns_rows(mini_warehouse):
    adapter = DuckDBAdapter(mini_warehouse.db_path)
    assert adapter.execute("SELECT 1") == [(1,)]
    adapter.close()


def test_empty_warehouse_graceful(tmp_path):
    adapter = DuckDBAdapter(tmp_path / "empty.duckdb")
    assert adapter.list_tables() == []
    assert adapter.describe_table("nope") == {}
    assert adapter.row_count("nope") == 0
    adapter.close()

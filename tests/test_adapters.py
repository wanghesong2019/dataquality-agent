"""WarehouseAdapter + DuckDBAdapter 测试。"""
import duckdb

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


def test_execute_max_rows_caps_materialized_rows(tmp_path):
    """execute(max_rows=N) 最多物化 N 行（fetchmany 而非 fetchall）——护栏的内存保护。"""
    adapter = DuckDBAdapter(tmp_path / "many.duckdb")
    adapter.execute("CREATE TABLE t AS SELECT * FROM range(1000) r(i)")
    assert len(adapter.execute("SELECT * FROM t", max_rows=7)) == 7
    assert len(adapter.execute("SELECT * FROM t")) == 1000
    adapter.close()


def test_wrapped_conn_survives_close_and_reuse(tmp_path):
    """包装外部 conn 的 adapter，close() 后复用应仍连原库（而非静默连内存库）。"""
    conn = duckdb.connect(str(tmp_path / "x.duckdb"))
    conn.execute("CREATE TABLE t AS SELECT 42 AS v")
    adapter = DuckDBAdapter(conn)
    adapter.close()
    assert adapter.execute("SELECT v FROM t") == [(42,)]


def test_execute_recovers_from_aborted_transaction():
    """一条失败的写语句 abort 事务后，adapter 后续读仍应可用（execute 内 rollback 兜底）。

    复现整改复检阶段的真实崩溃：LLM 生成的 fix_sql 执行失败 → DuckDB「Current transaction
    is aborted」→ 后续 run_detection 的 list_tables 直接抛异常。修复后 execute 失败即回滚。
    """
    conn = duckdb.connect()
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER)")
    conn.execute("INSERT INTO t VALUES (1, 10)")
    adapter = DuckDBAdapter(conn)

    conn.execute("BEGIN")
    try:
        adapter.execute("INSERT INTO t VALUES (1, 20)")  # duplicate PK → 失败
    except Exception:
        pass

    # 关键断言：事务已 abort，但 adapter 后续只读不能被毒化
    assert adapter.list_tables() == ["t"]
    assert adapter.row_count("t") == 1

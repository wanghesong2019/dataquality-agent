import pytest

from dataquality_agent.adapters import DuckDBAdapter
from dataquality_agent.tools.sql import SafeSQL, SQLGuardError, validate_sql


@pytest.fixture
def safe(mini_warehouse):
    return SafeSQL(DuckDBAdapter(mini_warehouse.db_path), whitelist={"orders", "order_items"})


def test_validate_sql_rejects_write():
    assert validate_sql("DELETE FROM orders", {"orders"}) == "only SELECT is allowed"
    assert validate_sql("UPDATE orders SET x=1", {"orders"}) == "only SELECT is allowed"


def test_validate_sql_rejects_multi_statement():
    assert validate_sql("SELECT * FROM orders; DROP TABLE orders", {"orders"}) == "multi-statement is not allowed"


def test_validate_sql_rejects_non_whitelist():
    assert validate_sql("SELECT * FROM payments", {"orders"}) == "table not in whitelist: payments"


def test_validate_sql_allows_read():
    assert validate_sql("SELECT * FROM orders", {"orders"}) == ""


def test_safe_sql_allows_read(safe):
    assert len(safe.run("SELECT * FROM orders")) == 3


def test_safe_sql_raises_on_write(safe):
    with pytest.raises(SQLGuardError):
        safe.run("DELETE FROM orders")


class _Recorder:
    """记录 SafeSQL 向 adapter 请求的 max_rows，观察护栏是否在物化前限行。"""

    def __init__(self):
        self.requested_max_rows = None

    def execute(self, sql, max_rows=None):
        self.requested_max_rows = max_rows
        return [(1,) for _ in range(max_rows if max_rows is not None else 100)]


def test_safe_sql_fetches_at_most_max_rows_plus_one():
    recorder = _Recorder()
    safe = SafeSQL(recorder, whitelist={"orders"}, max_rows=2)
    with pytest.raises(SQLGuardError):
        safe.run("SELECT * FROM orders")
    # 护栏应请求 max_rows+1 行（多一行用于探测是否超限），而非整表 fetchall
    assert recorder.requested_max_rows == 3

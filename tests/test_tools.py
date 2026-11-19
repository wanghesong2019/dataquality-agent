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

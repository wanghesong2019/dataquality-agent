"""PostgresAdapter（psycopg3）四原语 + 生命周期测试。需 POSTGRES_DSN，否则跳过。"""
import os

import pytest

psycopg = pytest.importorskip("psycopg")
from dataquality_agent.adapters.postgres import PostgresAdapter

DSN = os.environ.get("POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="POSTGRES_DSN not set")


@pytest.fixture
def pg():
    conn = psycopg.connect(DSN)
    conn.execute("DROP TABLE IF EXISTS t")
    conn.commit()
    yield conn
    conn.execute("DROP TABLE IF EXISTS t")
    conn.commit()
    conn.close()


def test_four_primitives(pg):
    pg.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    pg.execute("INSERT INTO t VALUES (1, 'a'), (2, NULL)")
    pg.commit()
    a = PostgresAdapter(pg)
    assert a.execute("SELECT id FROM t ORDER BY id") == [(1,), (2,)]
    assert "t" in a.list_tables()
    assert a.describe_table("t") == {"id": "integer", "name": "text"}
    assert a.row_count("t") == 2


def test_nonexistent_table_graceful(pg):
    a = PostgresAdapter(pg)
    assert a.describe_table("nope") == {}
    assert a.row_count("nope") == 0


def test_max_rows_caps_materialization(pg):
    pg.execute("CREATE TABLE t AS SELECT generate_series(1, 1000) AS i")
    pg.commit()
    a = PostgresAdapter(pg)
    assert len(a.execute("SELECT * FROM t", max_rows=7)) == 7
    assert len(a.execute("SELECT * FROM t")) == 1000


def test_execute_recovers_from_failed_statement(pg):
    pg.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    pg.commit()
    a = PostgresAdapter(pg)
    try:
        a.execute("INSERT INTO t VALUES (1), (1)")  # duplicate PK -> error
    except Exception:
        pass
    # connection must still serve reads (the failed statement was rolled back)
    assert "t" in a.list_tables()
    assert a.row_count("t") == 0


def test_wrapped_conn_survives_close(pg):
    pg.execute("CREATE TABLE t AS SELECT 42 AS v")
    pg.commit()
    a = PostgresAdapter(pg)
    a.close()  # must NOT close the wrapped conn
    assert a.execute("SELECT v FROM t") == [(42,)]


def test_describe_table_parameterized(pg):
    pg.execute("CREATE TABLE t (id INTEGER)")
    pg.commit()
    a = PostgresAdapter(pg)
    assert a.describe_table("t; DROP TABLE t") == {}  # treated as a literal
    assert "t" in a.list_tables()                     # table survived

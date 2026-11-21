"""Postgres 集成：L0 层在真实 Postgres 上产出与 DuckDB 同构的 Evidence 异常。需 POSTGRES_DSN，否则跳过。"""
import os

import pytest

psycopg = pytest.importorskip("psycopg")
from dataquality_agent.adapters.postgres import PostgresAdapter
from dataquality_agent.detection.rules import run_rule_checks, run_consistency_checks
from dataquality_agent.models import Evidence

DSN = os.environ.get("POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="POSTGRES_DSN not set")


def test_l0_isomorphic_to_duckdb(postgres_warehouse):
    adapter = PostgresAdapter(postgres_warehouse)
    # clean mini data: no L0 anomalies, same as DuckDB
    assert run_rule_checks(adapter) + run_consistency_checks(adapter) == []
    # inject multiple anomaly types -> each detected with structured Evidence, isomorphic to DuckDB
    postgres_warehouse.execute("INSERT INTO orders SELECT * FROM orders LIMIT 1")            # duplicate
    postgres_warehouse.execute("DELETE FROM products WHERE product_id = 'p1'")               # orphan (referential)
    postgres_warehouse.execute("UPDATE order_items SET price = -5.0 WHERE order_id = 'o1'")  # value_range
    postgres_warehouse.execute("UPDATE orders SET customer_id = NULL WHERE order_id = 'o1'") # not_null
    anomalies = run_rule_checks(adapter) + run_consistency_checks(adapter)
    assert {"duplicate", "orphan", "value_range", "null_rate"} <= {a.type for a in anomalies}
    for a in anomalies:
        assert isinstance(a.evidence, Evidence) and a.evidence.query.strip()

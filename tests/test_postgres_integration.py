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
    # inject a duplicate -> structured Evidence, isomorphic to DuckDB
    postgres_warehouse.execute("INSERT INTO orders SELECT * FROM orders LIMIT 1")
    postgres_warehouse.commit()
    anomalies = run_rule_checks(adapter)
    dup = [a for a in anomalies if a.type == "duplicate"]
    assert dup and isinstance(dup[0].evidence, Evidence)
    assert dup[0].evidence.query.strip() and dup[0].evidence.rows

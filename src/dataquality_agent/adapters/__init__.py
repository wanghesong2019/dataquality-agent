"""WarehouseAdapter 抽象 + DuckDB 参考实现 + Postgres（psycopg3）实现。"""
from dataquality_agent.adapters.base import WarehouseAdapter
from dataquality_agent.adapters.duckdb import DuckDBAdapter
from dataquality_agent.adapters.postgres import PostgresAdapter

__all__ = ["WarehouseAdapter", "DuckDBAdapter", "PostgresAdapter"]

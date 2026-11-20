"""WarehouseAdapter 抽象与 DuckDB 参考实现。"""
from dataquality_agent.adapters.base import WarehouseAdapter
from dataquality_agent.adapters.duckdb import DuckDBAdapter

__all__ = ["WarehouseAdapter", "DuckDBAdapter"]

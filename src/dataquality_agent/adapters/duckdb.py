"""DuckDBAdapter：WarehouseAdapter 的 DuckDB 参考实现。"""
from pathlib import Path

import duckdb

from dataquality_agent.adapters.base import WarehouseAdapter


class DuckDBAdapter(WarehouseAdapter):
    """基于 DuckDB 文件的适配器（懒连接，可显式 close）。"""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._conn = None

    def connect(self) -> None:
        if self._conn is None:
            self._conn = duckdb.connect(self.path)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _ensure(self):
        self.connect()
        return self._conn

    def execute(self, sql: str) -> list[tuple]:
        return self._ensure().execute(sql).fetchall()

    def list_tables(self) -> list[str]:
        rows = self._ensure().execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        return [r[0] for r in rows]

    def describe_table(self, table: str) -> dict[str, str]:
        if table not in self.list_tables():
            return {}
        rows = self._ensure().execute(f"DESCRIBE {table}").fetchall()
        return {r[0]: r[1] for r in rows}

    def row_count(self, table: str) -> int:
        if table not in self.list_tables():
            return 0
        return self._ensure().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

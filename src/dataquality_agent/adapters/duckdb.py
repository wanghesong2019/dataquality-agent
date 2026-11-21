"""DuckDBAdapter：WarehouseAdapter 的 DuckDB 参考实现。"""
from pathlib import Path

import duckdb

from dataquality_agent.adapters.base import WarehouseAdapter


class DuckDBAdapter(WarehouseAdapter):
    """基于 DuckDB 的适配器：可接文件路径（懒连接），也可直接包一个已存在的连接（供注入写+检测读共享同一 conn）。"""

    def __init__(self, path_or_conn):
        self._owns_conn = isinstance(path_or_conn, (str, Path))
        if self._owns_conn:
            self.path = str(path_or_conn)
            self._conn = None
        else:
            self.path = None
            self._conn = path_or_conn

    def connect(self) -> None:
        if self._conn is None:
            self._conn = duckdb.connect(self.path)

    def close(self) -> None:
        if not self._owns_conn:
            return  # 包装外部连接：不关、不置空，所有权在调用方
        if self._conn is not None:
            self._conn.close()
        self._conn = None

    def _ensure(self):
        self.connect()
        return self._conn

    def execute(self, sql: str, max_rows: int | None = None) -> list[tuple]:
        conn = self._ensure()
        try:
            cur = conn.execute(sql)
            return cur.fetchmany(max_rows) if max_rows is not None else cur.fetchall()
        except Exception:
            # 写语句失败会 abort 当前事务（DuckDB 需 ROLLBACK 才能继续）；回滚兜底，
            # 别让单条坏 SQL 毒化连接、拖垮后续只读（复检阶段曾因此抛 TransactionException）。
            try:
                conn.rollback()
            except Exception:
                pass
            raise

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

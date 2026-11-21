"""PostgresAdapter：WarehouseAdapter 的 psycopg3 实现（第一个真实引擎连接器）。"""
from pathlib import Path

from dataquality_agent.adapters.base import WarehouseAdapter


class PostgresAdapter(WarehouseAdapter):
    """基于 psycopg3 的适配器：可接 libpq DSN（懒连接），也可直接包一个已存在的 psycopg.Connection。"""

    def __init__(self, dsn_or_conn):
        self._owns_conn = isinstance(dsn_or_conn, (str, Path))
        if self._owns_conn:
            self.dsn = str(dsn_or_conn)
            self._conn = None
        else:
            self.dsn = None
            self._conn = dsn_or_conn

    def connect(self) -> None:
        if self._conn is None:
            import psycopg  # 可选依赖：懒导入，没装 psycopg 时 import 本模块不炸

            self._conn = psycopg.connect(self.dsn)

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
            try:
                return cur.fetchmany(max_rows) if max_rows is not None else cur.fetchall()
            finally:
                cur.close()
        except Exception:
            # 失败语句会 abort 当前隐式事务（Postgres 需 ROLLBACK 才能继续）；回滚兜底，
            # 别让单条坏 SQL 毒化连接、拖垮后续只读（对齐 DuckDBAdapter 的同名兜底）。
            try:
                conn.rollback()
            except Exception:
                pass
            raise

    def list_tables(self) -> list[str]:
        rows = self._ensure().execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
        return [r[0] for r in rows]

    def describe_table(self, table: str) -> dict[str, str]:
        # 参数化 %s 防注入；限定 public schema（与 list_tables/row_count 一致）；表不存在返回空 dict
        cur = self._ensure().execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
            (table,),
        )
        return {r[0]: r[1] for r in cur.fetchall()}

    def row_count(self, table: str) -> int:
        if table not in self.list_tables():
            return 0
        return self._ensure().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

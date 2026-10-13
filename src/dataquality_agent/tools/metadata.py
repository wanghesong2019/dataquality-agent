"""元数据/血缘查询工具。"""


def get_table_schema(conn, table: str) -> dict[str, str]:
    """返回 {列名: 类型}（用 DESCRIBE）。"""
    rows = conn.execute(f"DESCRIBE {table}").fetchall()
    return {r[0]: r[1] for r in rows}


def get_tables(conn) -> list[str]:
    """列出所有表名。"""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return [r[0] for r in rows]


def get_row_count(conn, table: str) -> int:
    """行数。"""
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

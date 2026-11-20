---
sidebar_position: 1
title: Connect a warehouse
description: Implement WarehouseAdapter to point DataAgent at your own database.
---

# Connect a warehouse

The core never talks to a database directly — every read goes through the `WarehouseAdapter` protocol. To point DataAgent at your warehouse, implement five methods. DuckDB ships as the reference implementation; the protocol is database-agnostic.

## The protocol

```python
class WarehouseAdapter(Protocol):
    def execute(self, sql: str, max_rows: int | None = None) -> list[tuple]: ...
    def list_tables(self) -> list[str]: ...
    def describe_table(self, table: str) -> dict[str, str]: ...
    def row_count(self, table: str) -> int: ...
```

- `execute` returns rows. Pass `max_rows` to cap how many rows are materialized (the `SafeSQL` guard relies on it to stay memory-safe).
- `describe_table` returns `{column: type}`; return `{}` for a missing table.
- `row_count` returns `0` for a missing table.

## Example: Postgres

```python
from dataquality_agent.adapters.base import WarehouseAdapter

class PostgresAdapter:
    def __init__(self, dsn: str):
        import psycopg
        self._conn = psycopg.connect(dsn)

    def execute(self, sql: str, max_rows: int | None = None) -> list[tuple]:
        cur = self._conn.cursor()
        cur.execute(sql)
        return cur.fetchmany(max_rows) if max_rows is not None else cur.fetchall()

    def list_tables(self) -> list[str]:
        rows = self.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        return [r[0] for r in rows]

    def describe_table(self, table: str) -> dict[str, str]:
        rows = self.execute(
            f"SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_name = '{table}'"
        )
        return {r[0]: r[1] for r in rows}

    def row_count(self, table: str) -> int:
        return self.execute(f"SELECT COUNT(*) FROM {table}")[0][0]
```

## Use it

```python
from dataquality_agent.detection.runner import run_detection

adapter = PostgresAdapter("postgresql://user:pass@host:5432/dw")
report = run_detection(adapter)
```

:::note
`execute` must return **tuples**, and `max_rows` must actually limit what is fetched — don't fetch the whole result and slice afterwards, or you lose the memory guard that makes agent-generated SQL safe.
:::

## Connector roadmap

| Adapter | Status |
|---|---|
| `DuckDBAdapter` | Reference implementation, ships with the core |
| Postgres | Next real engine (v0.2) |
| StarRocks | v0.3 |
| Trino / Spark | v0.4+ |

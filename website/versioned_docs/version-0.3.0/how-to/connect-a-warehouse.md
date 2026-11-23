---
sidebar_position: 1
title: Connect a warehouse
description: Point DQAgent at your own database through WarehouseAdapter.
---

# Connect a warehouse

The core never talks to a database directly — every read goes through the `WarehouseAdapter` protocol. Two adapters ship with the core: `DuckDBAdapter` (the reference) and `PostgresAdapter` (psycopg3). For any other engine, implement the four methods below.

## Built-in adapters

### DuckDB

```python
from dataquality_agent.adapters import DuckDBAdapter

adapter = DuckDBAdapter("warehouse.duckdb")   # owns and lazily opens the file
adapter = DuckDBAdapter(existing_conn)         # wraps a connection it does not own
```

### Postgres

```bash
pip install dataquality-agent[postgres]
```

```python
from dataquality_agent.adapters import PostgresAdapter

adapter = PostgresAdapter("postgresql://user:pass@host:5432/dw")   # a libpq DSN, opened lazily
adapter = PostgresAdapter(existing_conn)                            # wraps an existing psycopg.Connection
```

A DSN-backed adapter opens lazily on first use and can be `close()`d; a connection-backed adapter never closes the shared connection.

## The protocol (implement a new engine)

```python
class WarehouseAdapter(Protocol):
    def execute(self, sql: str, max_rows: int | None = None) -> list[tuple]: ...
    def list_tables(self) -> list[str]: ...
    def describe_table(self, table: str) -> dict[str, str]: ...
    def row_count(self, table: str) -> int: ...
```

- `execute` returns rows. Pass `max_rows` to cap how many rows are materialized (the `SafeSQL` guard relies on it to stay memory-safe) — limit the fetch, don't fetch everything and slice.
- `describe_table` returns `{column: type}`; return `{}` for a missing table.
- `row_count` returns `0` for a missing table.

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
| `PostgresAdapter` | Ships with the core (`[postgres]` extra, psycopg3) |
| StarRocks | v0.4 |
| Trino / Spark | v0.5+ |

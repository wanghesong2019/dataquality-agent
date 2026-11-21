---
sidebar_position: 2
title: Warehouse adapter
description: Reference for the WarehouseAdapter protocol and DuckDBAdapter.
---

# Warehouse adapter

`WarehouseAdapter` is the only interface the core uses to read a warehouse.

```python
class WarehouseAdapter(Protocol):
    def execute(self, sql: str, max_rows: int | None = None) -> list[tuple]: ...
    def list_tables(self) -> list[str]: ...
    def describe_table(self, table: str) -> dict[str, str]: ...
    def row_count(self, table: str) -> int: ...
```

## Methods

### `execute(sql, max_rows=None)`

Run a query and return rows as `list[tuple]`.

- `max_rows` caps how many rows are materialized. The `SafeSQL` guard passes `max_rows + 1` to detect overflow, so a compliant adapter must limit the fetch — not fetch everything and slice.
- Return `[]` for statements with no result set.

### `list_tables()`

All table names in the warehouse.

### `describe_table(table)`

`{column_name: data_type}`. Return `{}` when the table does not exist.

### `row_count(table)`

Number of rows. Return `0` when the table does not exist.

## `DuckDBAdapter` (reference)

The reference implementation accepts either a **path** or an **existing connection**:

```python
from dataquality_agent.adapters import DuckDBAdapter

adapter = DuckDBAdapter("warehouse.duckdb")   # owns and lazily opens the file
adapter = DuckDBAdapter(existing_conn)         # wraps a connection it does not own
```

- A path-backed adapter opens lazily on first use and can be `close()`d.
- A connection-backed adapter (`close()` sets the handle to `None` without closing the shared connection) is used internally so the data injector and the detectors share one connection.

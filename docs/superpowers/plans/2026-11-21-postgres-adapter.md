# PostgresAdapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `PostgresAdapter` (psycopg3) implementing the `WarehouseAdapter` four primitives so the kernel can run the deterministic L0 layer against a real Postgres warehouse.

**Architecture:** Mirror `DuckDBAdapter`'s constructor (wrap an existing `psycopg.Connection` or a libpq DSN), implement the four primitives against `information_schema` and psycopg cursors; add `psycopg[binary]` as an optional dependency. Proven by loading the mini Olist ODS tables into Postgres and running the L0 layer to produce `Evidence`-carrying anomalies isomorphic to DuckDB.

**Tech Stack:** Python 3.10+, psycopg (v3), pytest, GitHub Actions `postgres` service, Docker (33-server).

**Spec:** `docs/specs/2026-11-21-v030-design.md` §4 (subsystem 1) + §6 acceptance P1/P2.

## Global Constraints

- `WarehouseAdapter` four primitives are frozen — `PostgresAdapter` implements only `execute` / `list_tables` / `describe_table` / `row_count`, no new methods (spec §3).
- Driver is psycopg3 (`psycopg[binary]`), NOT psycopg2, NOT SQLAlchemy (spec §8).
- psycopg is an **optional** dependency (`[project.optional-dependencies] postgres`); DuckDB stays the zero-dependency reference (spec §4).
- No SQL dialect translation layer; `describe_table` returns the engine's raw type names, un-normalized (spec §4, §8).
- Read-only: `execute` never mutates the warehouse; `describe_table` parameterizes the table name with `%s` against injection (spec §4).
- Tests **skip** (not fail) when `POSTGRES_DSN` is unset, so the existing 218-test suite stays green on a bare machine (spec §6 P5).
- Existing tests must stay green.

## Review Focus

The input classes / failure modes most likely to bite a person using `PostgresAdapter`:

1. `describe_table("nonexistent")` → `{}`, `row_count("nonexistent")` → `0`, `list_tables()` on an empty schema → `[]`, no exception (mirrors DuckDB; spec §4). → Task A1.
2. A failed `execute` (syntax error / violated constraint) must not poison later reads — the adapter rolls back the aborted implicit transaction, exactly like DuckDB's `execute` (spec §4; the DuckDB analog caused a real eval crash). → Task A1.
3. `execute(sql, max_rows=N)` caps materialized rows via `fetchmany(N)`; `max_rows=None` returns all via `fetchall` (P2 read-only memory guard). → Task A1.
4. Wrapping an external `psycopg.Connection`, `close()` must NOT close it (ownership stays with the caller), matching DuckDB's wrapped-conn semantics. → Task A1.
5. `describe_table` must parameterize the table name so a hostile identifier (`"t; DROP TABLE t"`) is treated as a literal and cannot inject SQL. → Task A1.

---

### Task A1: PostgresAdapter (four primitives + lifecycle)

**Files:**
- Modify: `pyproject.toml` — add `postgres = ["psycopg[binary]>=3.1"]` to `[project.optional-dependencies]`.
- Create: `src/dataquality_agent/adapters/postgres.py`
- Modify: `src/dataquality_agent/adapters/__init__.py` — export `PostgresAdapter`.
- Test: `tests/test_postgres_adapter.py`

**Interfaces:**
- Consumes: `WarehouseAdapter` protocol (`src/dataquality_agent/adapters/base.py`) — the four methods and their exact signatures.
- Produces: `PostgresAdapter(dsn_or_conn)` with `execute(self, sql, max_rows=None) -> list[tuple]`, `list_tables() -> list[str]`, `describe_table(table) -> dict[str, str]`, `row_count(table) -> int`, plus `connect()`, `close()`, `_ensure()`.

- [ ] **Step 1: Write the failing tests** in `tests/test_postgres_adapter.py`

```python
import os

import pytest

psycopg = pytest.importorskip("psycopg")
from dataquality_agent.adapters.postgres import PostgresAdapter

DSN = os.environ.get("POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="POSTGRES_DSN not set")


@pytest.fixture
def pg():
    conn = psycopg.connect(DSN)
    conn.execute("DROP TABLE IF EXISTS t")
    conn.commit()
    yield conn
    conn.execute("DROP TABLE IF EXISTS t")
    conn.commit()
    conn.close()


def test_four_primitives(pg):
    pg.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    pg.execute("INSERT INTO t VALUES (1, 'a'), (2, NULL)")
    pg.commit()
    a = PostgresAdapter(pg)
    assert a.execute("SELECT id FROM t ORDER BY id") == [(1,), (2,)]
    assert "t" in a.list_tables()
    assert a.describe_table("t") == {"id": "integer", "name": "text"}
    assert a.row_count("t") == 2


def test_nonexistent_table_graceful(pg):
    a = PostgresAdapter(pg)
    assert a.describe_table("nope") == {}
    assert a.row_count("nope") == 0


def test_max_rows_caps_materialization(pg):
    pg.execute("CREATE TABLE t AS SELECT generate_series(1, 1000) AS i")
    pg.commit()
    a = PostgresAdapter(pg)
    assert len(a.execute("SELECT * FROM t", max_rows=7)) == 7
    assert len(a.execute("SELECT * FROM t")) == 1000


def test_execute_recovers_from_failed_statement(pg):
    pg.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    pg.commit()
    a = PostgresAdapter(pg)
    try:
        a.execute("INSERT INTO t VALUES (1), (1)")  # duplicate PK -> error
    except Exception:
        pass
    # connection must still serve reads (the failed statement was rolled back)
    assert "t" in a.list_tables()
    assert a.row_count("t") == 0


def test_wrapped_conn_survives_close(pg):
    pg.execute("CREATE TABLE t AS SELECT 42 AS v")
    pg.commit()
    a = PostgresAdapter(pg)
    a.close()  # must NOT close the wrapped conn
    assert a.execute("SELECT v FROM t") == [(42,)]


def test_describe_table_parameterized(pg):
    pg.execute("CREATE TABLE t (id INTEGER)")
    pg.commit()
    a = PostgresAdapter(pg)
    assert a.describe_table("t; DROP TABLE t") == {}  # treated as a literal
    assert "t" in a.list_tables()                     # table survived
```

- [ ] **Step 2: Run to verify they fail** — `POSTGRES_DSN=... pytest tests/test_postgres_adapter.py -v` → FAIL: `ModuleNotFoundError: No module named 'dataquality_agent.adapters.postgres'` (with DSN set; without it every test skips).

- [ ] **Step 3: Implement** `PostgresAdapter` in `src/dataquality_agent/adapters/postgres.py`

  - Constructor mirrors `DuckDBAdapter`: `dsn_or_conn` is `str`/`Path` → own it lazily (`_conn = None`); otherwise wrap the existing `psycopg.Connection`. Track `self._owns_conn`.
  - `connect()` / `close()` / `_ensure()` mirror DuckDB (lazy `psycopg.connect(self.dsn)`; `close()` is a no-op when wrapping an external conn).
  - `execute(sql, max_rows=None)`: `cur = self._ensure().execute(sql)`, then `cur.fetchmany(max_rows) if max_rows is not None else cur.fetchall()`, close the cursor; on any exception, `self._ensure().rollback()` inside an inner try/except, then re-raise — psycopg3's `Connection.execute` returns a cursor and a failed statement aborts the implicit transaction, so this is the direct analog of DuckDB's aborted-transaction recovery.
  - `list_tables()`: `SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'` → `[r[0] for r in rows]`.
  - `describe_table(table)`: `SELECT column_name, data_type FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position` with `%s` parameterization → `{col: type}` (empty `{}` when no rows, i.e. nonexistent table).
  - `row_count(table)`: `if table not in self.list_tables(): return 0`; else `SELECT COUNT(*) FROM {table}` → `int`.
  - Export `PostgresAdapter` from `adapters/__init__.py`.

- [ ] **Step 4: Run to verify pass** — `POSTGRES_DSN=... pytest tests/test_postgres_adapter.py -v` → PASS.

- [ ] **Step 5: Add the optional dependency to `pyproject.toml` and commit.**

---

### Task A2: Postgres integration — L0 layer produces isomorphic Anomalies

**Files:**
- Modify: `tests/conftest.py` — add a `postgres_warehouse` fixture (loads the mini Olist ODS tables into Postgres; skip if no DSN).
- Test: `tests/test_postgres_integration.py`

**Interfaces:**
- Consumes: `PostgresAdapter` (Task A1); the `mini_data` fixture (writes the 8 ODS CSVs); `run_rule_checks` / `run_consistency_checks` from `dataquality_agent.detection.rules`.

- [ ] **Step 1: Write the failing test** in `tests/test_postgres_integration.py`

```python
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
```

- [ ] **Step 2: Run to verify fail** — `POSTGRES_DSN=... pytest tests/test_postgres_integration.py -v` → FAIL: fixture `postgres_warehouse` not found.

- [ ] **Step 3: Implement the `postgres_warehouse` fixture** in `tests/conftest.py`

  - Skip if `POSTGRES_DSN` unset. Connect via psycopg.
  - Create the 8 ODS tables (orders, order_items, payments, reviews, products, sellers, customers, geolocation) with explicit types, following one rule: **timestamp columns → `TIMESTAMP`, numeric columns → `DOUBLE PRECISION` / `INTEGER`, everything else `TEXT`**. The only type-sensitive columns are `orders`' four timestamps — `order_purchase_timestamp`, `order_approved_at`, `order_delivered_carrier_date`, `order_delivered_customer_date`, `order_estimated_delivery_date` — which MUST be `TIMESTAMP` (not `TEXT`) so `check_future_date`'s `> DATE '2018-12-31'` and `check_time_inversion`'s `<` behave as DuckDB's auto-detected `TIMESTAMP` does. (Concretely: `orders.order_purchase_timestamp`, `orders.order_approved_at`, `orders.order_delivered_carrier_date`, `orders.order_delivered_customer_date`, `orders.order_estimated_delivery_date`, `order_items.shipping_limit_date`, `reviews.review_creation_date`, `reviews.review_answer_timestamp` → `TIMESTAMP`; `order_items.price`/`freight_value`, `products.product_weight_g`/`_length_cm`/`_height_cm`/`_width_cm`, `payments.payment_value`, `geolocation.geolocation_lat`/`_lng` → `DOUBLE PRECISION`; `order_items.order_item_id`, `payments.payment_sequential`/`payment_installments`, `reviews.review_score`, `products.product_*_lenght`/`_photos_qty` → `INTEGER`; everything else `TEXT`.)
  - Load each table from the CSV `mini_data` already wrote, via `cursor.copy_expert("COPY <table> FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')", io.BytesIO(csv_bytes))`.
  - `yield` the psycopg connection; teardown drops the 8 tables and closes.

- [ ] **Step 4: Run to verify pass** — `POSTGRES_DSN=... pytest tests/test_postgres_integration.py -v` → PASS.

- [ ] **Step 5: Commit.**

---

### Task A3: CI + 33-server test wiring

**Files:**
- Modify: `.github/workflows/ci.yml`
- (Docs only) the connect-33-server skill's project recipe, or a README note.

**Interfaces:** none (config only).

- [ ] **Step 1: Add the `postgres` service to CI.** In `jobs.test`, add `services.postgres` (`postgres:16`, healthcheck `pg_isready -U postgres`, `POSTGRES_PASSWORD: postgres`) and set `env: POSTGRES_DSN: postgresql://postgres:postgres@localhost:5432/postgres` for the test step. Change the Install step to `pip install -e ".[dev,postgres]"` so psycopg is present.

- [ ] **Step 2: Add the 33-server Docker recipe** — a documented one-liner: `docker run --name dqa-postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d postgres:16`, with `POSTGRES_DSN=postgresql://postgres:postgres@localhost:5432/postgres`, appended to the connect-33-server skill's project recipe (or the repo README's "Testing" note). Do not commit any secret.

- [ ] **Step 3: Verify** — run `pytest -q` without DSN (all Postgres tests skip; 218 stay green), then with DSN (new tests run). Commit.

# Contributing to DQAgent

Thanks for your interest in contributing to **DQAgent** (`dataquality-agent`)! DQAgent is built on one principle: **everything is an assertion; every judgment is evidence-backed.** Whether you add a declarative L0 rule, build a warehouse adapter, improve root-cause diagnosis, or fix a typo in the docs, you're welcome here.

## 1. Local development setup

DQAgent requires **Python ≥ 3.10** and is licensed under **Apache-2.0**.

```bash
git clone https://github.com/<your-username>/dataquality-agent.git
cd dataquality-agent

python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev,postgres]"
```

Verify the CLI works:

```bash
dqagent init --dir ./demo            # scaffold sample data + .env
dqagent detect --dir ./demo          # no-LLM L0/L1 detection
```

CLI entry points (each takes a required `--dir`):

| Command | What it does |
|---|---|
| `dqagent init` | Scaffold sample data and a local `.env` |
| `dqagent detect` | Deterministic L0/L1 detection, **no LLM key needed**; `--assertions <yaml>` loads a declarative catalog |
| `dqagent run` | Full patrol loop (`assert → diagnose → remediate → approve`), needs an LLM key |
| `dqagent eval` | Deterministic no-LLM evaluation, prints detection P/R/F1 |

## 2. Running tests

DQAgent uses `pytest` (`testpaths = ["tests"]`, `pythonpath = ["src"]`). The suite is currently **240 tests**. Run it before opening a PR:

```bash
pytest                       # full suite
pytest tests/test_catalog.py # one file
pytest -k "adapter"          # filter by keyword
```

Postgres tests are gated on the `POSTGRES_DSN` env var and **skip gracefully** when it is unset — no local Postgres required to contribute.

## 3. Code style & conventions

- **Deterministic first.** Rules before statistics, statistics before LLM. Never introduce an LLM call where a deterministic SQL query or statistical check yields an exact answer.
- **Evidence-backed outputs.** Every anomaly or diagnosis must carry its proof — the SQL executed, offending rows/aggregates, and expected-vs-actual values (`Evidence`).
- **Type annotations.** Use Python 3.10+ hints (`list[...]`, `dict[...]`, `X | None`) on public interfaces.
- **Minimal, focused diffs.** One feature / adapter / rule set / fix per PR. Update docs under `website/docs/` when you change user-facing behavior or configuration.

## 4. The four extension seams

DQAgent is designed so you can extend it without touching the core orchestration loop:

| Seam | What you implement |
|---|---|
| `WarehouseAdapter` | connect a SQL engine — `execute` / `list_tables` / `describe_table` / `row_count` |
| `Detector` | `name` + `detect(adapter, ctx) -> list[Anomaly]` |
| `RemediationPolicy` | how a diagnosis becomes a fix, and its risk |
| `CaseStore` / RAG | a store of past incidents for root-cause retrieval |

## 5. Adding a check — declare it first

**The lowest-friction contribution is a declarative L0 assertion in YAML — no Python `Detector` required.** Five built-in types map to the `check_*` reference implementations:

| Type | Purpose |
|---|---|
| `unique` | uniqueness over a column or composite key |
| `not_null` | reject any `NULL` in a critical column |
| `null_rate` | cap the allowed `NULL` ratio (0–1) |
| `value_range` | numeric/date bounds (`min` and/or `max`) |
| `referential` | foreign-key integrity against a parent table |

```yaml
# assertions.yaml
assertions:
  - name: fact_orders_unique_order_id
    type: unique
    table: fact_orders
    columns: [order_id]                     # list — composite keys too

  - name: fact_orders_customer_not_null
    type: not_null
    table: fact_orders
    column: customer_id

  - name: fact_orders_discount_null_rate
    type: null_rate
    table: fact_orders
    column: discount_code
    max_rate: 0.15
    where: "order_status = 'completed'"     # optional raw SQL WHERE fragment

  - name: fact_orders_amount_non_negative
    type: value_range
    table: fact_orders
    column: total_amount
    min: 0
    max: 1000000

  - name: fact_orders_ref_dim_customers
    type: referential
    child_table: fact_orders
    child_column: customer_id
    parent_table: dim_customers
    # parent_column defaults to child_column; set it only when the names differ
```

Each assertion needs a unique `name` and a `type`. Optional `severity` (`low` / `medium` / `high`) is stamped onto any anomaly it raises. **Write a Python `Detector` only when** your check needs multi-step logic, cross-window time-series comparison, or statistics that YAML can't express.

## 6. Adding a warehouse adapter

Adding a new engine (ClickHouse, StarRocks, Doris, Snowflake, BigQuery, MySQL, …) is one of the highest-impact contributions.

Read the two shipped references first: `DuckDBAdapter` (canonical in-process) and `PostgresAdapter` (psycopg3, external/networked).

Implement the four `WarehouseAdapter` protocol primitives:

```python
def execute(self, sql: str, max_rows: int | None = None) -> list[tuple]: ...
def list_tables(self) -> list[str]: ...
def describe_table(self, table: str) -> dict[str, str]:   # {column: type}; {} if missing
def row_count(self, table: str) -> int:                   # 0 if missing
```

Also implement the lifecycle helpers the other adapters expose: `connect()` (open lazily on first use) and `close()` (release the connection).

Then:

1. **Respect SafeSQL.** All runtime SQL is SELECT-only, table-allowlisted, and row-capped. Never bypass it or issue DDL/DML inside adapter primitives.
2. **Keep the driver optional.** Don't add heavy drivers to core `dependencies`; add them under `[project.optional-dependencies]` (like the existing `postgres = ["psycopg[binary]>=3.1"]`).
3. **Test all four primitives** under `tests/` — return shapes, `describe_table` type mapping, and error handling — with local fixtures or mocks so `pytest` runs without cloud credentials.
4. **Document it** in `website/docs/reference/warehouse-adapter.md`.

## 7. Pull request workflow

1. Branch from `master` with a descriptive name: `feat/<…>`, `adapter/<warehouse>`, `fix/<…>`, `docs/<…>`.
2. Make atomic commits; ensure `pytest` passes locally with no regressions.
3. Open a PR against `master`, describe **what** changed and **why**, and link any issue (`Closes #<n>`). For new adapters or detectors, include sample output or test evidence.

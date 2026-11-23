---
sidebar_position: 5
title: Run eval on your warehouse
description: Point the deterministic evaluation harness at your own warehouse and calibrate an injection plan.
---

# Run eval on your warehouse

`dqagent eval` (and the CI F1 gate) ships with a tiny self-contained sample — the 3-order mini Olist that `dqagent init` generates. To measure detection quality against your own data, point the harness at your warehouse and give it your own injection plan.

## 1. Point the harness at your warehouse

`run_deterministic_eval(settings, injection_specs)` takes a `Settings` and an injection plan. `Settings` needs two things: `data_dir` (where your CSV source tables live) and `db_path` (where the DuckDB warehouse should be built). Note this harness is DuckDB-specific — the build, inject, and clone steps all run on DuckDB. The `PostgresAdapter` (v0.3.0) lets `run_detection` inspect a real Postgres, but the deterministic eval harness does not drive it yet.

```python
from dataquality_agent.config import Settings
from dataquality_agent.eval.deterministic import run_deterministic_eval

settings = Settings(data_dir="/path/to/your/csvs", db_path="/path/to/warehouse.duckdb")
report = run_deterministic_eval(settings, injection_specs=[...])  # your plan
print(report.detection)  # DetectionMetrics(precision=..., recall=..., f1=...)
```

## 2. Calibrate your injection plan

`injection_specs` is a list of dicts, one per anomaly you plant. The count `n` must be calibrated to your data volume — a rate-based check only fires once enough injected rows cross its threshold. `null_rate` triggers above 5%, so with ~99k delivered orders you need ~6k nulled rows, not 1:

```python
{"type": "null_rate", "table": "orders", "column": "order_delivered_customer_date",
 "status_col": "order_status", "status_value": "delivered", "key_cols": ["order_id"], "n": 6000}
```

Two gotchas worth knowing:

- **One injection can trigger several detections.** Setting `order_items.price` negative also breaks the cross-table `amount_mismatch` check (payment total vs item total), which the eval then scores as a false positive. Pick injection columns that are checked by exactly one rule (e.g. `products.product_weight_g` for `value_range`).
- **Subtract your known baseline.** Real data often has pre-existing issues (e.g. a handful of payment mismatches). The harness captures these on the clean warehouse *before* injection and subtracts them, so they aren't scored as your false positives.

## 3. Two databases — don't confuse them

DQAgent uses two databases, and only one is about your data:

| What | Where | Pluggable today? |
|---|---|---|
| The warehouse you inspect | `WarehouseAdapter` (DuckDB · Postgres) | Yes — `DuckDBAdapter` / `PostgresAdapter` ship with the core |
| HITL approval state (checkpoints + run registry) | SQLite (`checkpoints.sqlite`, `runs.sqlite`) | v0.1 SQLite only |

The SQLite state store is still the only backend. You can move it with the `CHECKPOINT_PATH` env var, but you can't swap the engine yet — the warehouse connector grew a Postgres in v0.3.0, but the HITL state store has not. LangGraph already ships a `PostgresSaver`, and `RunStore` will grow a pluggable backend alongside it.

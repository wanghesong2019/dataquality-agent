---
sidebar_position: 5
title: Run eval on your warehouse
description: Point the deterministic evaluation harness at your own warehouse and calibrate an injection plan.
---

# Run eval on your warehouse

`dqagent eval` (and the CI F1 gate) ships with a tiny self-contained sample — the 3-order mini Olist that `dqagent init` generates. To measure detection quality against your own data, point the harness at your warehouse and give it your own injection plan.

## 1. Point the harness at your warehouse

`run_deterministic_eval(settings, injection_specs)` takes a `Settings` and an injection plan. `Settings` needs two things: `data_dir` (where your CSV source tables live) and `db_path` (where the DuckDB warehouse should be built). In v0.1 the warehouse is DuckDB; v0.2 adds a Postgres `WarehouseAdapter` so this same harness runs against a real engine.

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

DataAgent uses two databases, and only one is about your data:

| What | Where | Pluggable today? |
|---|---|---|
| The warehouse you inspect | `WarehouseAdapter` (DuckDB in v0.1) | Yes — Postgres in v0.2 |
| HITL approval state (checkpoints + run registry) | SQLite (`checkpoints.sqlite`, `runs.sqlite`) | v0.1 SQLite only |

The SQLite state store is the v0.1 reference implementation. You can move it with the `CHECKPOINT_PATH` env var, but you can't swap the engine yet. Production teams typically run this on Postgres; that arrives with v0.2 — LangGraph already ships a `PostgresSaver`, and `RunStore` will grow a pluggable backend alongside it.

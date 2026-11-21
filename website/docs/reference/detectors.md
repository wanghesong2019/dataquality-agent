---
sidebar_position: 3
title: Detectors
description: Reference for the Detector protocol and the built-in detectors.
---

# Detectors

A detector is a single pluggable check. All detectors run against the warehouse through the `WarehouseAdapter`.

```python
class Detector(Protocol):
    name: str
    def detect(self, adapter, ctx: dict) -> list[Anomaly]: ...
```

## Registry

Built-in detectors register themselves in `DETECTORS` (`dataquality_agent.detection.base`). Order in the dict is execution order. Register your own with `DETECTORS["my_check"] = MyDetector()`.

## Built-in detectors

| Name | Layer | What it checks |
|---|---|---|
| `l0_rules` | L0 (rules) | Duplicate keys, orphan foreign keys, negative/out-of-range values, time inversion, future dates, null-rate (optionally status-stratified) |
| `l0_cross_table` | L0 (rules) | Cross-table consistency |
| `l1_lineage` | L1 (statistical) | Lineage breaks — upstream data stops flowing |
| `l1_freshness` | L1 (statistical) | Stale watermarks (data stops updating) |
| `l1_schema` | L1 (statistical) | Schema drift vs an expected snapshot |
| `l1_volume` | L1 (statistical) | Volume anomalies (z-score) |
| `l1_distribution` | L1 (statistical) | Distribution drift (chi-square) |
| `l2_semantic` | L2 (LLM) | Semantic anomalies (requires `semantic_model`) |

L0 is deterministic and 0-LLM; L1 is statistical and 0-LLM; L2 needs an LLM.

## Declarative L0 assertions

The `l0_rules` detector is driven by an **assertion catalog** — a YAML file that declares the generic L0 checks, so you don't write a `Detector` for them. Five types, mapping to the same `check_*` reference implementations:

```yaml
# assertions.yaml
version: 1
assertions:
  - name: orders_unique_order_id
    type: unique
    table: orders
    columns: [order_id]
  - name: orders_customer_not_null
    type: not_null
    table: orders
    column: customer_id
  - name: orders_delivered_date_null_rate
    type: null_rate
    table: orders
    column: order_delivered_customer_date
    max_rate: 0.05
    where: "order_status = 'delivered'"
  - name: order_items_price_non_negative
    type: value_range
    table: order_items
    column: price
    min: 0
  - name: order_items_ref_products
    type: referential
    child_table: order_items
    child_column: product_id
    parent_table: products
```

| Type | Required fields | Optional |
|---|---|---|
| `unique` | `table`, `columns` (1..n) | `severity` |
| `not_null` | `table`, `column` | `severity` |
| `null_rate` | `table`, `column`, `max_rate` | `where`, `severity` |
| `value_range` | `table`, `column`, `min`/`max` (≥1) | `severity` |
| `referential` | `child_table`, `child_column`, `parent_table` | `parent_column` (defaults to `child_column`), `severity` |

Pass it with `dqagent detect --assertions assertions.yaml` or `run_detection(assertions_path=...)`. A user catalog **replaces** the bundled Olist default (17 assertions) — list the defaults too if you want them. Every assertion still emits a structured `Evidence` on fail.

## The `Anomaly` contract

```python
class Anomaly(BaseModel):
    type: str                 # duplicate / orphan / value_range / null_rate / time_inversion / future_date / …
    table: str
    column: str | None = None
    severity: str = "medium"  # low / medium / high
    evidence: Evidence         # structured: query + rows + expected vs actual + lineage/blast-radius
    metric_value: float | str | None = None
    expected_range: str | None = None
```

`evidence` is a structured [`Evidence`](/docs/reference/detectors#the-evidence-object) object, not a string; `anomaly.summary` returns the legacy human-readable text.

## The `Evidence` object

Every conclusion carries its proof as a structured `Evidence`, not prose:

```python
class Evidence(BaseModel):
    query: str = ""                   # the SQL that triggered the verdict
    rows: list[dict] | None = None     # offending-row sample (capped at 20)
    expected: str | None = None        # what should be
    actual: str | None = None          # what is
    lineage: list[str] | None = None   # upstream lineage (attribution fills this)
    blast_radius: list[str] | None = None  # downstream impact (attribution fills this)
```

Detection populates `query`/`rows`/`expected`/`actual`; attribution later fills `lineage`/`blast_radius`. A detector should set `query` and, where it sampled rows, `rows` — an anomaly with neither is a bare conclusion and violates the philosophy.

## `run_detection`

```python
def run_detection(adapter, detectors=None, *,
                  current_date=None, expected_schema=None, semantic_model=None,
                  zscore_threshold=None, distribution_alpha=None,
                  null_rate_threshold=None, assertions_path=None) -> DetectionReport
```

- `detectors` — overrides the registry (default: all built-ins).
- `expected_schema` — `{table: {column: type}}` snapshot for `l1_schema`; omitted skips it.
- `semantic_model` — an object with `.chat` for `l2_semantic`; omitted skips it.
- `zscore_threshold` / `distribution_alpha` — default from `Settings`.
- `null_rate_threshold` — default from `Settings`; drives the default catalog's delivered-date null-rate check.
- `assertions_path` — YAML path for the declarative L0 catalog; omitted uses the bundled default.

Returns `DetectionReport(anomalies, stats)` where `stats[name]` is that detector's wall-clock seconds, or `-1.0` if the detector raised (isolated — one failure never aborts the patrol).

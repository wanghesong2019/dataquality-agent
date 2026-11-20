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

## The `Anomaly` contract

```python
class Anomaly(BaseModel):
    type: str                 # duplicate / orphan / value_range / null_rate / time_inversion / future_date / …
    table: str
    column: str | None = None
    severity: str = "medium"  # low / medium / high
    evidence: str = ""
    metric_value: float | str | None = None
    expected_range: str | None = None
```

## `run_detection`

```python
def run_detection(adapter, detectors=None, *,
                  current_date=None, expected_schema=None, semantic_model=None,
                  zscore_threshold=None, distribution_alpha=None) -> DetectionReport
```

- `detectors` — overrides the registry (default: all built-ins).
- `expected_schema` — `{table: {column: type}}` snapshot for `l1_schema`; omitted skips it.
- `semantic_model` — an object with `.chat` for `l2_semantic`; omitted skips it.
- `zscore_threshold` / `distribution_alpha` — default from `Settings`.

Returns `DetectionReport(anomalies, stats)` where `stats[name]` is that detector's wall-clock seconds, or `-1.0` if the detector raised (isolated — one failure never aborts the patrol).

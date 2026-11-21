---
sidebar_position: 2
title: Write a detector
description: Add your own check as a pluggable Detector.
---

# Write a detector

A detector is a single check: a `name` plus a `detect(adapter, ctx)` method that returns a list of `Anomaly` objects. Register it once and every patrol runs it, in the order you registered it.

## Declare first (L0)

For the five generic L0 check types — `unique`, `not_null`, `null_rate`, `value_range`, `referential` — you don't write a detector: you **declare** the check in YAML and pass it with `dqagent detect --assertions` (or `run_detection(assertions_path=...)`). The framework compiles each declaration into an evidence-carrying check against the same `check_*` reference implementations. See the [Detectors reference](/docs/reference/detectors#declarative-l0-assertions).

Reach for a custom detector only when your check is *not* one of those five — a cross-table formula, a statistical baseline, or semantic logic.

## The protocol

```python
class Detector(Protocol):
    name: str
    def detect(self, adapter, ctx: dict) -> list[Anomaly]: ...
```

`ctx` carries shared context computed once per patrol: `watermarks`, `current_date`, `zscore_threshold`, `distribution_alpha`, `expected_schema`, `semantic_model`.

## Example: flag non-positive GMV

```python
from dataquality_agent.detection.base import DETECTORS
from dataquality_agent.models import Anomaly

class GmvDropDetector:
    name = "gmv_drop"

    def detect(self, adapter, ctx):
        total = adapter.execute("SELECT SUM(gmv) FROM daily_metrics")[0][0]
        if total is None or total <= 0:
            return [Anomaly(
                type="value_range",
                table="daily_metrics",
                column="gmv",
                severity="high",
                evidence="daily_metrics.gmv is non-positive",
            )]
        return []

DETECTORS["gmv_drop"] = GmvDropDetector()
```

Now `run_detection(adapter)` includes it alongside the eight built-ins.

## Run only your detectors

```python
report = run_detection(adapter, detectors={"gmv_drop": GmvDropDetector()})
```

## The `Anomaly` contract

```python
class Anomaly(BaseModel):
    type: str                # duplicate / orphan / value_range / null_rate / …
    table: str
    column: str | None = None
    severity: str = "medium" # low / medium / high
    evidence: Evidence        # structured: query + rows + expected vs actual + lineage/blast-radius
    metric_value: float | str | None = None
    expected_range: str | None = None
```

`evidence` is a structured `Evidence` object (not a string) — pass the triggering query and offending rows so the anomaly is evidence-backed, not a bare conclusion.

## Failure isolation

A detector that raises does **not** abort the patrol. Its stage is marked failed (`stats[name] == -1.0`) and the others still run.

:::note
Keep detectors deterministic where possible. The three-layer principle is *rules before statistics, statistics before LLM* — put deterministic logic in a detector, and leave the expensive LLM for attribution.
:::

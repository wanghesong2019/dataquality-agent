# Changelog

All notable changes to this project will be documented in this file.

## [0.2.0] - 2026-11-20

Land the design philosophy **"一切皆断言，判断皆有据"** (*everything is an assertion; every judgment is evidence-backed*): evidence becomes a first-class structured object, and attribution is thinned to a single evidence-consuming LLM call.

### Added

- `Evidence` model (`query` / `rows` / `expected` / `actual` / `lineage` / `blast_radius`) — first-class structured evidence mounted on `Anomaly`, `Diagnosis`, and `Remediation`.
- Detection-layer row sampling: every L0 rule and cross-table consistency check captures offending rows (`LIMIT 20`) on fail, via `sample_offending`.
- `assemble_evidence`: deterministic, no-LLM evidence assembly (anomaly evidence + upstream lineage + schema + similar cases).
- `make_thin_diagnose_node`: thin attribution — one LLM call per anomaly consuming the assembled evidence package.
- Evidence-completeness gate in deterministic eval (every failed anomaly carries a non-empty `query`, `rows` capped at 20).

### Changed

- `Anomaly.evidence` is now `Evidence` (was a free-text `str`); a `summary` property returns the legacy human-readable text, and a `field_validator` shim keeps legacy `str` producers working.
- `wiring.py` builds the linear `build_graph` (inspect → thin diagnose → remediate → approve → report) instead of the supervisor triage + 3-specialist graph. Supervisor/specialist modules are retained as an eval comparison arm.
- L1 statistical detectors (`volume` / `distribution` / `lineage_break` / `freshness` / `schema_drift`) emit structured `Evidence` (no row sampling; `expected`/`actual` populated).
- `EvalReport` exposes `anomalies`.

## [0.1.1] - 2026-11-20

Patch release: clear the deferred minors from the v0.1.0 review.

### Fixed

- `run_detection` no longer crashes on a non-Olist warehouse — `_watermarks` skips missing tables instead of querying `dwd_orders`/`daily_metrics` unconditionally.
- `null_rate_threshold` is wired through `Settings` → `run_detection` → L0 rules (was a dead config; default corrected to 0.05).
- `dqagent eval` runs the no-LLM deterministic evaluation and prints detection P/R/F1 (was a stub).
- `total_latency` no longer counts failed detectors (marked `-1.0`) as elapsed time.
- `RunStore` serializes writes with a lock and a connection timeout, fixing occasional `database is locked` under concurrent access.
- A wrapped external connection survives `DuckDBAdapter.close()` — reuse no longer reconnects to an in-memory database.

### Added

- Deterministic detection F1 gate as a CI test (`tests/test_deterministic_eval.py`) — runs `run_deterministic_eval` on self-contained sample data and asserts F1 == 1.0.
- `eval/deterministic.py`: reusable `run_deterministic_eval(settings, injection_specs)` + `SAMPLE_INJECTION_SPECS`.
- How-to doc: run eval on your own warehouse.

## [0.1.0] - 2026-11-19

First open-source release: extract a pluggable core from the demo, out-of-the-box CLI, and deterministic CI.

### Added

- `WarehouseAdapter` protocol + `DuckDBAdapter` reference implementation (kernel reads warehouses only through the adapter).
- `Detector` protocol + registry; L0/L1/L2 detection registered as pluggable detectors with per-detector failure isolation.
- `dqagent` CLI: `init` (sample data + config), `detect` (no-LLM L0/L1), `run` (full patrol), `eval`.
- Persistent `RunStore`: restart-safe `list_runs` / `approve` for the HITL workflow.
- Deterministic no-LLM evaluation mode (`run_eval(llm=False)`) and GitHub Actions CI gate.

### Changed

- `SafeSQL`, tooling, agents, eval, and scripts now consume `WarehouseAdapter` instead of raw DuckDB connections.
- Detection thresholds (`zscore_threshold`, `distribution_alpha`) wired from `Settings`.

### Removed

- `tools/metadata.py` (its `DESCRIBE` / `information_schema` logic moved into `DuckDBAdapter`).

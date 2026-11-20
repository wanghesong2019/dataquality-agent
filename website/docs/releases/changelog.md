---
sidebar_position: 1
title: Changelog
description: Release notes for DataAgent.
---

# Changelog

All notable changes are recorded here. The project follows [Semantic Versioning](https://semver.org/): `0.x` allows breaking changes; `1.0` freezes the public API, CLI, and evaluation methodology.

## [0.1.1] — 2026-11-20

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

## [0.1.0] — 2026-11-19

First open-source release: a pluggable core extracted from the demo, an out-of-the-box CLI, and a deterministic CI gate.

### Added

- `WarehouseAdapter` protocol + `DuckDBAdapter` reference implementation — the kernel reads warehouses only through the adapter.
- `Detector` protocol + registry; L0/L1/L2 detection registered as pluggable detectors with per-detector failure isolation.
- `dqagent` CLI: `init` (sample data + config), `detect` (no-LLM L0/L1), `run` (full patrol), `eval`.
- Persistent `RunStore`: restart-safe `list_runs` / `approve` for the HITL workflow.
- Deterministic no-LLM evaluation mode (`run_eval(llm=False)`) and GitHub Actions CI gate.

### Changed

- `SafeSQL`, tooling, agents, eval, and scripts now consume `WarehouseAdapter` instead of raw DuckDB connections.
- Detection thresholds (`zscore_threshold`, `distribution_alpha`) wired from `Settings`.

### Fixed

- `SafeSQL` row cap now limits the fetch (`fetchmany`) instead of materializing the whole result set first, restoring its memory protection for whitelisted `SELECT *` on large warehouses.

### Removed

- `tools/metadata.py` — its `DESCRIBE` / `information_schema` logic moved into `DuckDBAdapter`.

---
sidebar_position: 1
title: Changelog
description: Release notes for DataAgent.
---

# Changelog

All notable changes are recorded here. The project follows [Semantic Versioning](https://semver.org/): `0.x` allows breaking changes; `1.0` freezes the public API, CLI, and evaluation methodology.

## [0.3.0] — 2026-11-21

First real warehouse connector + declarative L0 assertion catalog — "everything is an assertion" moves from a runtime structure to a configuration-time declaration.

### Added

- `PostgresAdapter` (psycopg3, `[postgres]` extra) — the four primitives against a real Postgres.
- Declarative L0 assertion catalog: YAML → `Assertion` → the `check_*` reference implementations (five types: `unique`/`not_null`/`null_rate`/`value_range`/`referential`).
- Default Olist catalog (17 assertions); `dqagent detect --assertions`; `run_detection(assertions_path=...)`.
- `deploy/warehouse/docker-compose.yml` + CI `postgres` service.

### Changed

- `run_rule_checks` = catalog checks + hardcoded time/future-date checks; `run_consistency_checks` = amount/state/zip only.
- `check_null_rate` accepts a raw `where` clause.

### Fixed

- Hardcoded time/future-date checks isolated — a non-Olist warehouse no longer discards the user's catalog results.
- `PostgresAdapter.describe_table` scoped to `public`.

## [0.2.1] — 2026-11-21

Patch release: fix a token-cost regression in the thin agent and a flaky eval crash.

### Fixed

- `Retriever.search` returned dense vectors that `assemble_evidence` serialized into every prompt (~32k tokens/call); now returns only `{id, text}`.
- Tool schemas no longer echo code-populated evidence fields.
- `DuckDBAdapter.execute` rolls back on failure, fixing the eval `TransactionException`.

### Measured

- Thin agent attribution 1.000 / ~85k tokens beats the supervisor 0.750 / ~228k (cost-normalized ~3.6×).

## [0.2.0] — 2026-11-20

Land the design philosophy — evidence becomes a first-class structured object; attribution thinned to a single evidence-consuming LLM call.

### Added

- `Evidence` model (`query`/`rows`/`expected`/`actual`/`lineage`/`blast_radius`).
- Detection-layer row sampling (`sample_offending`) on every L0 fail.
- `assemble_evidence` + `make_thin_diagnose_node` (one LLM call per anomaly).

### Changed

- `Anomaly.evidence` is now `Evidence` (was `str`).
- `wiring.py` builds the linear thin-agent graph (supervisor retained as an eval arm).

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

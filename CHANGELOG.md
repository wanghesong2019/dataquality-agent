# Changelog

All notable changes to this project will be documented in this file.

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

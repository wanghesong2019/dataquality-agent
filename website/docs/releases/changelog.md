---
sidebar_position: 1
title: Changelog
description: Release notes for DataAgent.
---

# Changelog

All notable changes are recorded here. The project follows [Semantic Versioning](https://semver.org/): `0.x` allows breaking changes; `1.0` freezes the public API, CLI, and evaluation methodology.

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

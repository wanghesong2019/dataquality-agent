---
sidebar_position: 4
title: Configuration
description: Reference for the Settings dataclass and environment variables.
---

# Configuration

All configuration lives in one `Settings` dataclass (`dataquality_agent.config`). Every path field can be overridden by an environment variable, which is how the Docker/`dqagent init` deployment stays portable.

## Paths

| Field | Env | Default |
|---|---|---|
| `data_dir` | `DATA_DIR` | `/data/home/hermes/olist` |
| `db_path` | `DB_PATH` | `…/dataquality-agent/data/warehouse.duckdb` |
| `checkpoint_path` | `CHECKPOINT_PATH` | `…/dataquality-agent/data/checkpoints.sqlite` |

## Detection thresholds

| Field | Default | Wired? |
|---|---|---|
| `zscore_threshold` | `3.0` | ✅ volume anomaly z-score |
| `distribution_alpha` | `0.05` | ✅ distribution drift chi-square p-value |
| `null_rate_threshold` | `0.20` | ⚠️ not wired (see below) |

## Reproducibility

| Field | Default | Meaning |
|---|---|---|
| `seed` | `42` | Random seed for the anomaly injector, so evaluations are reproducible |

## A note on `null_rate_threshold`

`null_rate_threshold` is declared but **not currently read** by the L0 null-rate checks. The built-in null-rate check uses per-column, semantically chosen thresholds (e.g. `0.05` for delivery-date, `0.0` for customer id) rather than one global value, because a single null-rate threshold across all columns produces false alarms. Until this is reconciled, treat the field as a placeholder — the L0 thresholds live in `detection/rules.py`.

## Loading a `.env`

`dqagent init` writes a `.env`, and `Settings.load_env(path)` reads it (KEY=VALUE, no dependency on `python-dotenv`). Existing environment variables are never overwritten.

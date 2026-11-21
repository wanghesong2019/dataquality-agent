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
| `null_rate_threshold` | `0.05` | ✅ delivered-date null-rate check (default catalog) |
| `assertions_path` | `None` | ✅ declarative L0 catalog (default: bundled Olist) |

## Reproducibility

| Field | Default | Meaning |
|---|---|---|
| `seed` | `42` | Random seed for the anomaly injector, so evaluations are reproducible |

## A note on `null_rate_threshold`

`null_rate_threshold` drives the **delivered-date** null-rate check in the default assertion catalog (`orders.order_delivered_customer_date`, `where order_status = 'delivered'`). The customer-id not-null check uses its own `0.0` threshold — per-column thresholds live in the catalog's assertions, not in one global value.

## Loading a `.env`

`dqagent init` writes a `.env`, and `Settings.load_env(path)` reads it (KEY=VALUE, no dependency on `python-dotenv`). Existing environment variables are never overwritten.

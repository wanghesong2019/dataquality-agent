---
sidebar_position: 1
title: CLI
description: Reference for the dqagent command-line interface.
---

# CLI

The `dqagent` command is the out-of-the-box entry point. Every subcommand takes a `--dir` pointing at a working directory.

```
dqagent <command> --dir <dir>
```

| Command | Purpose | Needs LLM key |
|---|---|---|
| `init` | Scaffold sample data + `.env` | no |
| `detect` | No-LLM detection (L0 rules + L1 statistical) | no |
| `run` | Full patrol (assert → diagnose → remediate → approve) | yes |
| `eval` | Deterministic evaluation | — |

## `init`

```bash
dqagent init --dir ./demo
```

Writes the bundled Olist sample warehouse and a `.env` into `./demo`. **Idempotent** — if the sample data already exists it is not overwritten. Exits 0.

## `detect`

```bash
dqagent detect --dir ./demo
```

Builds the warehouse and runs the deterministic layers only (no LLM, no key). Prints each anomaly and its evidence, then a total. Exits 0 on success, 1 if the sample data is missing.

```text
[null_rate] dwd_orders.order_delivered_customer_date delivered null rate 0.50
[volume] daily_metrics.orders volume z-score 4.2
7 anomalies
```

### Declare your own L0 assertions

```bash
dqagent detect --dir ./demo --assertions assertions.yaml
```

`--assertions` points at a YAML assertion catalog (see the [Detectors reference](/docs/reference/detectors#declarative-l0-assertions)); it **replaces** the bundled Olist default. No key needed.

## `run`

```bash
DEEPSEEK_API_KEY=… dqagent run --dir ./demo
```

Runs the full patrol — assert, assemble evidence, diagnose, remediate, approve. Returns the run id and status — `awaiting_approval` when a high-risk fix paused the pipeline for human approval.

```text
run_id=3f9a2c1d status=awaiting_approval
```

## `eval`

```bash
dqagent eval --dir ./demo
```

Runs the deterministic evaluation (no LLM) against the sample warehouse and prints detection precision / recall / F1 — the same gate the CI enforces.

```text
detection P/R/F1: P=1.000 R=1.000 F1=1.000
```

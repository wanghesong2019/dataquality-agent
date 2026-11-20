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
| `run` | Full patrol (inspect → attribute → remediate → approve) | yes |
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
[l0_rules] dwd_orders.delivered null-rate spike (status=canceled)
[l1_volume] daily_metrics.orders volume z-score 4.2
共 7 条异常
```

## `run`

```bash
DEEPSEEK_API_KEY=… dqagent run --dir ./demo
```

Runs the full supervisor pipeline. Returns the run id and status — `awaiting_approval` when a high-risk fix paused the pipeline for human approval.

```text
run_id=3f9a2c1d status=awaiting_approval
```

## `eval`

```bash
dqagent eval --dir ./demo
```

:::warning Not yet implemented
`eval` is a placeholder in this release — it prints a notice and exits 0. Deterministic detection evaluation is available through the eval harness (`scripts/run_eval.py --no-llm`) and is enforced by the test suite. Wiring `eval` to the harness is on the roadmap.
:::

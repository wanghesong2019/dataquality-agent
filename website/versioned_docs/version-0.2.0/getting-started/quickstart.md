---
sidebar_position: 1
title: Quickstart
description: Get DQAgent detecting, attributing, and remediating data issues in five minutes.
---

# Quickstart

DQAgent is an **agentic data quality** pipeline. It upgrades rule-and-manual governance into a closed loop — *assert → diagnose → remediate → approve → report* — where every judgment carries its evidence. At runtime it **only proposes** — high-risk fixes wait behind a human approval gate, and it never writes to your production warehouse.

This guide gets you from install to a full patrol in five minutes, using the bundled sample warehouse and **no API key**.

## Prerequisites

- Python 3.10+
- Optional: a DeepSeek API key (`DEEPSEEK_API_KEY`) for the full LLM pipeline (`dqagent run`)

## 1. Install

```bash
pip install dataquality-agent
```

## 2. Scaffold sample data and config

```bash
dqagent init --dir ./demo
```

This writes the bundled Olist sample warehouse and a `.env` into `./demo`. It is idempotent — re-running it never overwrites existing data.

## 3. Detect (no LLM, no key)

```bash
dqagent detect --dir ./demo
```

Runs the deterministic layers — L0 rules and L1 statistical checks — and prints every anomaly with its evidence:

```text
[null_rate] dwd_orders.order_delivered_customer_date delivered null rate 0.50
[volume] daily_metrics.orders volume z-score 4.2
7 anomalies
```

## 4. Run the full patrol (LLM)

```bash
dqagent run --dir ./demo
```

Sets `DEEPSEEK_API_KEY` first. This runs the whole loop: detection (with evidence captured on failure), deterministic evidence assembly, a single attribution call, remediation, and — for high-risk fixes — pauses for human approval.

```text
run_id=3f9a2c1d status=awaiting_approval
```

## Next steps

- **[Philosophy](/docs/philosophy)** — the worldview behind it all.
- **[Architecture](/docs/concepts/architecture)** — the layered design and where each piece lives.
- **[Core flow](/docs/concepts/core-flow)** — the assertion lifecycle, stage by stage.
- **[Extension points](/docs/concepts/extension-points)** — where you plug in your warehouse, checks, and fix logic.
- **[CLI reference](/docs/reference/cli)** — every command and flag.

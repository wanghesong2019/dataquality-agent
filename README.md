<div align="center">
  <img src="assets/logo.png" alt="DataAgent" width="110" />

  <h1>DataAgent</h1>

  <p><em>Agentic Data Quality — Inspect · Attribute · Remediate</em></p>

  <p>
    <a href="https://wanghesong2019.github.io/dataquality-agent/"><img alt="Docs" src="https://img.shields.io/badge/docs-online-orange" /></a>
    <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-blue" />
    <img alt="Apache 2.0" src="https://img.shields.io/badge/License-Apache_2.0-blue" />
    <a href="https://github.com/wanghesong2019/dataquality-agent/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/wanghesong2019/dataquality-agent/actions/workflows/ci.yml/badge.svg" /></a>
  </p>
</div>

---

An open-source, out-of-the-box **data quality agent** that upgrades traditional rule-and-manual data governance into an **LLM-agent pipeline**: inspect → attribute → remediate → human approval → report.

> **Documentation**: [wanghesong2019.github.io/dataquality-agent](https://wanghesong2019.github.io/dataquality-agent/)

> **Positioning**: at runtime, it **proposes, never executes** — the agent generates remediation plans, high-risk fixes go through human approval, and plan effectiveness is verified **offline** (apply the plan on a cloned warehouse and re-check to get a remediation success rate). It never mutates your production warehouse directly.

## Why

Traditional data-quality tools (Great Expectations, Soda, Deequ, Griffin) **detect** but don't **attribute root cause or close the remediation loop**. Metadata catalogs (OpenMetadata, DataHub) have lineage and quality checks but no multi-agent attribution. This project fills that gap: **agentic data quality** — a pluggable framework where multi-agent orchestration turns "a check failed" into "here's why, here's the fix, and here's the approval gate".

## Architecture

```
┌  Thin platform shell (optional)  dqagent serve → FastAPI + dashboard + HITL
├────────────────────────────────────────────────────────────
├  Core library  dataquality_agent  (pip install / import)
│    Detectors (L0 rules · L1 statistical · L2 semantic)      ← pluggable
│    Multi-agent attribution (supervisor triage + specialists)
│    Remediation (Executor + Critic) · HITL approval · Report
│        │  all reads go through one interface
│        ▼
│    WarehouseAdapter  (connect · read-only query · metadata)
│        ├─ DuckDBAdapter (reference)   └─ (roadmap) Postgres / StarRocks / …
└  Observability  step-level trace + cost ledger
```

**Four pluggable seams**: `WarehouseAdapter` (connect a warehouse) · `Detector` (add a check) · `RemediationPolicy` (teach it how to fix) · `CaseStore/RAG` (domain knowledge).

## Quickstart

```bash
pip install dataquality-agent

# 1. scaffold sample data + local config
dqagent init --dir ./demo

# 2. no-LLM detection (L0 rules + L1 statistical, no API key needed)
dqagent detect --dir ./demo

# 3. full patrol (inspect → attribute → remediate → approve), needs DEEPSEEK_API_KEY
dqagent run --dir ./demo
```

## Features

- **Three-layer detection** — L0 deterministic rules (null/unique/range/referential/cross-table) · L1 statistical (freshness/volume/distribution/schema/lineage) · L2 LLM semantic.
- **Multi-agent attribution** — supervisor triage dispatches each anomaly to a focused specialist (lineage / SQL / case retrieval), then aggregates findings into a root-cause diagnosis.
- **Remediation + HITL** — Executor + Critic generate risk-graded fixes; high-risk fixes require human approval (`only-propose, never-execute`).
- **Read-only SQL guard** — every agent SQL goes through `SafeSQL` (SELECT-only, table whitelist, row cap).
- **Evaluation harness** — quantified detection F1 / attribution accuracy / remediation success (reversible vs data-loss split) / end-to-end / cost-latency.

## Evaluation

| Metric | Result |
|---|---|
| Detection F1 | **1.0** (deterministic, injector ground-truth) |
| Attribution / remediation / end-to-end | quantified by the eval harness (needs a DeepSeek key + warehouse data) |

Run the deterministic no-LLM gate locally: `pytest -q` (194 tests) — it runs the injector's ground-truth against detection on the bundled sample data.

## Project structure

```
src/dataquality_agent/
├── adapters/        # WarehouseAdapter protocol + DuckDBAdapter
├── detection/       # Detector protocol + registry, L0/L1/L2
├── agents/          # supervisor triage, specialists, diagnose, remediate, hitl, report
├── eval/            # metrics, judge, harness, trajectory
├── api/             # FastAPI app, PatrolRuntime + RunStore, wiring
├── data/            # warehouse builder, lineage, injector, sample
├── tools/           # SafeSQL read-only guard
├── rag/             # retriever, embedder, rerank
└── cli.py           # dqagent CLI (init/detect/run/eval)
```

## License

[Apache License 2.0](LICENSE)

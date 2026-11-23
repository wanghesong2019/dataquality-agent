<div align="center">
  <img src="assets/logo.png" alt="DQAgent" width="110" />

  <h1>DQAgent</h1>

  <p><em>Data Quality Agent — everything is an assertion; every judgment is evidence-backed</em></p>

  <p>
    <a href="https://wanghesong2019.github.io/dataquality-agent/"><img alt="Docs" src="https://img.shields.io/badge/docs-online-orange" /></a>
    <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-blue" />
    <img alt="Apache 2.0" src="https://img.shields.io/badge/License-Apache_2.0-blue" />
    <a href="https://github.com/wanghesong2019/dataquality-agent/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/wanghesong2019/dataquality-agent/actions/workflows/ci.yml/badge.svg" /></a>
  </p>
</div>

---

An open-source, out-of-the-box **data quality agent** that upgrades traditional rule-and-manual data governance into an **LLM-agent pipeline**: assert → diagnose → remediate → human approval → report.

> **Documentation**: [wanghesong2019.github.io/dataquality-agent](https://wanghesong2019.github.io/dataquality-agent/) · **Roadmap**: [ROADMAP.md](ROADMAP.md)

> **Positioning**: at runtime, it **proposes, never executes** — the agent generates remediation plans, high-risk fixes go through human approval, and plan effectiveness is verified **offline** (apply the plan on a cloned warehouse and re-check to get a remediation success rate). It never mutates your production warehouse directly.

## Why

Traditional data-quality tools (Great Expectations, Soda, Deequ, Griffin) **detect** but don't **attribute root cause or close the remediation loop**. Metadata catalogs (OpenMetadata, DataHub) have lineage and quality checks but no agentic attribution. This project fills that gap: **agentic data quality** — a pluggable framework where every judgment carries its evidence, turning "a check failed" into "here's why, here's the fix, and here's the approval gate".

## Architecture

```
┌  Thin platform shell (optional)  dqagent serve → FastAPI + dashboard + HITL
├────────────────────────────────────────────────────────────
├  Core library  dataquality_agent  (pip install / import)
│    Detectors (L0 rules · L1 statistical · L2 semantic)      ← pluggable
│    Thin attribution (deterministic evidence assembly + one LLM call)
│    Remediation (Executor + Critic) · HITL approval · Report
│        │  all reads go through one interface
│        ▼
│    WarehouseAdapter  (connect · read-only query · metadata)
│        ├─ DuckDBAdapter (reference) · PostgresAdapter (psycopg3)
│        └─ (roadmap) StarRocks / …
└  Observability  step-level trace + cost ledger
```

**Four pluggable seams**: `WarehouseAdapter` (connect a warehouse) · `Detector` (add a check) · `RemediationPolicy` (teach it how to fix) · `CaseStore/RAG` (domain knowledge).

## Warehouse support

The kernel reads every warehouse through the one `WarehouseAdapter` interface (four read-only primitives: `execute` / `list_tables` / `describe_table` / `row_count`). Adding an engine is a self-contained, high-impact contribution.

| Engine | Adapter | Status |
|---|---|---|
| DuckDB | `DuckDBAdapter` (in-core reference) | ✅ Supported |
| PostgreSQL | `PostgresAdapter` (psycopg3, `[postgres]` extra) | ✅ Supported (v0.3.0) |
| StarRocks | — | 🚧 Roadmap |
| ClickHouse · Doris · MySQL · Snowflake · BigQuery · Hive · Spark · Flink | — | 🙋 Help wanted — see [adding an adapter](CONTRIBUTING.md#6-adding-a-warehouse-adapter) |

## Quickstart

```bash
pip install dataquality-agent

# 1. scaffold sample data + local config
dqagent init --dir ./demo

# 2. no-LLM detection (L0 rules + L1 statistical, no API key needed)
dqagent detect --dir ./demo

# 3. full patrol (assert → diagnose → remediate → approve), needs DEEPSEEK_API_KEY
dqagent run --dir ./demo
```

## Features

- **Three-layer detection** — L0 deterministic rules (null/unique/range/referential/cross-table) · L1 statistical (freshness/volume/distribution/schema/lineage) · L2 LLM semantic.
- **Declarative L0 assertions** — declare `unique` / `not_null` / `null_rate` / `value_range` / `referential` checks in YAML; the framework compiles them into evidence-carrying detectors (`dqagent detect --assertions`).
- **Warehouse connectors** — `DuckDBAdapter` (reference) + `PostgresAdapter` (psycopg3); the kernel reads every warehouse through the one `WarehouseAdapter` interface.
- **Thin attribution** — a deterministic step assembles an evidence package (anomaly evidence + lineage + schema + similar cases), then a single LLM call turns it into a root-cause diagnosis.
- **Remediation + HITL** — Executor + Critic generate risk-graded fixes; high-risk fixes require human approval (`only-propose, never-execute`).
- **Read-only SQL guard** — every agent SQL goes through `SafeSQL` (SELECT-only, table whitelist, row cap).
- **Evaluation harness** — quantified detection F1 / attribution accuracy / remediation success (reversible vs data-loss split) / end-to-end / cost-latency.

## Evaluation

On the bundled Olist benchmark (21 injected anomalies, `deepseek-chat` at temperature 0), the thin evidence-first agent is measured to beat the multi-agent supervisor it replaced:

| Metric | Thin agent | Supervisor (multi-agent) |
|---|---|---|
| Attribution accuracy | **1.000** | 0.750 |
| Tokens | **~85k** | ~228k |
| Latency | **~107s** | ~210s |
| LLM calls | **~67** | ~141 |
| Cost-normalized attribution | **~3.6× better** | — |

Detection F1 is **1.0** (deterministic; the same injector ground-truth gates CI). The thin agent is a *measured* choice, not a stylistic one — see [the philosophy](https://wanghesong2019.github.io/dataquality-agent/docs/philosophy). One caveat: these are benchmark numbers, not a universal claim.

Run the deterministic no-LLM gate locally: `pytest -q` (240 tests) — it runs the injector's ground-truth against detection on the bundled sample data.

## Project structure

```
src/dataquality_agent/
├── adapters/        # WarehouseAdapter protocol + DuckDBAdapter + PostgresAdapter
├── detection/       # Detector protocol + registry, L0/L1/L2 + declarative catalog
├── agents/          # inspect, thin diagnose, remediate, hitl, report
├── eval/            # metrics, judge, harness, trajectory
├── api/             # FastAPI app, PatrolRuntime + RunStore, wiring
├── data/            # warehouse builder, lineage, injector, sample
├── tools/           # SafeSQL read-only guard
├── rag/             # retriever, embedder, rerank
└── cli.py           # dqagent CLI (init/detect/run/eval)
```

## Contributing

Contributions are welcome — no PR is too small. The two lowest-friction ways in:

- **Add a check** — declare a `unique` / `not_null` / `null_rate` / `value_range` / `referential` assertion in YAML (no Python needed).
- **Add a warehouse adapter** — implement the four `WarehouseAdapter` primitives for a new engine (see the [support matrix](#warehouse-support) above).

See [CONTRIBUTING.md](CONTRIBUTING.md) for local setup, tests, and conventions; [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community norms.

## Contributors

<a href="https://github.com/wanghesong2019/dataquality-agent/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wanghesong2019/dataquality-agent" alt="Contributors" />
</a>

## License

[Apache License 2.0](LICENSE)

---

<details>
<summary><strong>中文文档（Chinese README）</strong></summary>

**Data Quality Agent —— 一切皆断言，判断皆有据**

一个开箱即用的开源**数据质量 Agent**，把传统的「规则 + 人工」数据治理升级为一条 **LLM-Agent 流水线**：断言 → 诊断 → 整改 → 人工审批 → 报告。

> **文档**: [wanghesong2019.github.io/dataquality-agent](https://wanghesong2019.github.io/dataquality-agent/) · **路线图**: [ROADMAP.md](ROADMAP.md)

> **定位**：运行时**只提案、不执行**——Agent 生成整改方案，高危修复需经人工审批，方案有效性在**离线**验证（在克隆数仓上应用方案并复检，得到整改成功率）。它从不直接改动你的生产数仓。

## 为什么做这个

传统数据质量工具（Great Expectations、Soda、Deequ、Griffin）只会**检测**，却不做**根因归因**、也走不完整改闭环。元数据目录（OpenMetadata、DataHub）有血缘和质量检查，但没有 Agent 化的归因能力。本项目补上的正是这个空白：**Agentic 数据质量**——一个可插拔框架，让每一次判断都携带证据，把「一条检查失败了」变成「为什么失败、怎么修、审批门禁在哪」。

## 架构

```
┌  Thin platform shell (optional)  dqagent serve → FastAPI + dashboard + HITL
├────────────────────────────────────────────────────────────
├  Core library  dataquality_agent  (pip install / import)
│    Detectors (L0 rules · L1 statistical · L2 semantic)      ← pluggable
│    Thin attribution (deterministic evidence assembly + one LLM call)
│    Remediation (Executor + Critic) · HITL approval · Report
│        │  all reads go through one interface
│        ▼
│    WarehouseAdapter  (connect · read-only query · metadata)
│        ├─ DuckDBAdapter (reference) · PostgresAdapter (psycopg3)
│        └─ (roadmap) StarRocks / …
└  Observability  step-level trace + cost ledger
```

**四个可插拔扩展缝**：`WarehouseAdapter`（接入数仓）· `Detector`（新增检查）· `RemediationPolicy`（教会它怎么修）· `CaseStore/RAG`（领域知识）。

## 数仓支持

内核通过唯一的 `WarehouseAdapter` 接口读取每一个数仓（四个只读原语：`execute` / `list_tables` / `describe_table` / `row_count`）。新增一个引擎是自包含、高价值的贡献。

| 引擎 | 适配器 | 状态 |
|---|---|---|
| DuckDB | `DuckDBAdapter`（内置参考实现） | ✅ 已支持 |
| PostgreSQL | `PostgresAdapter`（psycopg3，`[postgres]` extra） | ✅ 已支持（v0.3.0） |
| StarRocks | — | 🚧 路线图中 |
| ClickHouse · Doris · MySQL · Snowflake · BigQuery · Hive · Spark · Flink | — | 🙋 求贡献——见[新增适配器](CONTRIBUTING.md#6-adding-a-warehouse-adapter) |

## 快速开始

```bash
pip install dataquality-agent

# 1. 生成样本数据 + 本地配置
dqagent init --dir ./demo

# 2. 无 LLM 检测（L0 规则 + L1 统计，无需 API key）
dqagent detect --dir ./demo

# 3. 完整巡检（断言 → 诊断 → 整改 → 审批），需要 DEEPSEEK_API_KEY
dqagent run --dir ./demo
```

## 特性

- **三层检测** —— L0 确定性规则（空值/唯一/值域/引用/跨表）· L1 统计（新鲜度/数据量/分布/schema/血缘）· L2 LLM 语义。
- **声明式 L0 断言** —— 用 YAML 声明 `unique` / `not_null` / `null_rate` / `value_range` / `referential` 检查，框架把它们编译成带证据的检测器（`dqagent detect --assertions`）。
- **数仓连接器** —— `DuckDBAdapter`（参考实现）+ `PostgresAdapter`（psycopg3）；内核通过唯一的 `WarehouseAdapter` 接口读取每一个数仓。
- **薄归因** —— 一个确定性步骤组装证据包（异常证据 + 血缘 + schema + 相似案例），再由一次 LLM 调用转成根因诊断。
- **整改 + HITL** —— Executor + Critic 生成按风险分级的修复方案；高危修复需人工审批（只提案、不执行）。
- **只读 SQL 护栏** —— 每条 Agent SQL 都经过 `SafeSQL`（仅 SELECT、表白名单、行数上限）。
- **评估框架** —— 量化检测 F1 / 归因准确率 / 整改成功率（可逆 vs 数据丢失分开）/ 端到端 / 成本-耗时。

## 评测

在随附的 Olist 基准（21 条注入异常，`deepseek-chat` temperature 0）上，薄证据优先 Agent 实测优于它取代的多 Agent supervisor：

| 指标 | 薄 Agent | Supervisor（多 Agent） |
|---|---|---|
| 归因准确率 | **1.000** | 0.750 |
| Tokens | **~85k** | ~228k |
| 耗时 | **~107s** | ~210s |
| LLM 调用 | **~67** | ~141 |
| 成本归一归因 | **~3.6× 更优** | — |

检测 F1 为 **1.0**（确定性；同一注入 ground-truth 作为 CI 门禁）。薄 Agent 是*实测*选择，不是风格偏好——见[设计哲学](https://wanghesong2019.github.io/dataquality-agent/docs/philosophy)。一点说明：以上是基准数据，不是普适承诺。

本地跑无 LLM 确定性门禁：`pytest -q`（240 个测试）——在随附样本数据上，用注入 ground-truth 验证检测。

## 项目结构

```
src/dataquality_agent/
├── adapters/        # WarehouseAdapter 协议 + DuckDBAdapter + PostgresAdapter
├── detection/       # Detector 协议 + registry，L0/L1/L2 + 声明式目录
├── agents/          # inspect、thin diagnose、remediate、hitl、report
├── eval/            # 指标、judge、harness、trajectory
├── api/             # FastAPI 应用，PatrolRuntime + RunStore，wiring
├── data/            # 数仓构建、血缘、注入器、样本
├── tools/           # SafeSQL 只读护栏
├── rag/             # retriever、embedder、rerank
└── cli.py           # dqagent CLI（init/detect/run/eval）
```

## 参与贡献

欢迎贡献——再小的 PR 都欢迎。两条最低门槛的参与方式：

- **加一条检查** —— 用 YAML 声明一条 `unique` / `not_null` / `null_rate` / `value_range` / `referential` 断言（无需写 Python）。
- **加一个数仓适配器** —— 为新引擎实现 `WarehouseAdapter` 的四个原语（见上方[支持矩阵](#warehouse-support)）。

环境搭建、测试、规范见 [CONTRIBUTING.md](CONTRIBUTING.md)；社区准则见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 许可证

[Apache License 2.0](LICENSE)

</details>

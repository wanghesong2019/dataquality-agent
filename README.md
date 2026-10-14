# DataAgent —— 数据质量巡检 · 异常归因 · 整改闭环

面向数仓的多 Agent 系统：把传统「规则 + 人工」的数据治理，升级为「LLM Agent 智能巡检 + 自动归因 + 审批整改」。

> **定位**：运行时**只提案、不执行**——「检测 → 归因 → 生成整改方案 → 高危人工审批 → 报告」，Agent 不直接改生产数仓；方案有效性由**离线评估**验证（副本数仓上「应用方案→复检」得整改成功率）。

## 技术栈

- **编排**：LangGraph（巡检→归因→整改→审批→报告，含 HITL interrupt/resume）
- **检测**：三层——L0 规则断言（确定性）｜ L1 统计可观测（freshness/volume/distribution/schema/lineage）｜ L2 LLM 语义
- **多 Agent**：巡检 / 归因（ReAct 工具循环，原生 function calling）/ 整改（风险分级）/ 审批（HITL）/ 报告
- **RAG**：Chroma + BM25 混合检索 → RRF 融合（embedding 走 BGE-M3）
- **结构化输出**：Pydantic → JSON Schema（function calling 强制）
- **可观测**：Trace + 成本台账（Langfuse 可插拔）
- **数据层**：DuckDB（轻量自包含）+ 异常注入器（ground-truth）
- **后端**：FastAPI + APScheduler 定时调度；前端原生 HTML/JS

## 架构

```
┌ 展示层   FastAPI 后端 + Web Dashboard（触发巡检/异常列表/归因/整改/审批按钮）
├ Agent 编排  LangGraph：巡检 → 归因(ReAct) → 整改(Critic) → 审批(HITL) → 报告
├ 能力层   工具(SQL只读/血缘/元数据/案例检索) · RAG · 结构化输出 · 护栏
├ 数据层   DuckDB 数仓(ODS/DWD/DWS) · 血缘元数据 · 异常注入器(ground-truth)
├ 可观测   Trace + 成本台账
└ 评估层   ground-truth 对比 + LLM-as-a-Judge
```

## 快速开始

### 1. 安装依赖

```bash
pip install -e ".[dev]"
```

### 2. 准备数据与配置

- Olist 数据（9 表 CSV）放到 `Settings.data_dir`（默认 `/data/home/hermes/olist`，可用 `DATA_DIR` env 覆盖）。
- 复制 `.env.example` 为 `.env`，填 `DEEPSEEK_API_KEY`、`EMBEDDING_*`。

### 3. 跑评估（出量化数字）

```bash
python scripts/run_eval.py
```

输出检测 F1 / 归因正确率 / 整改成功率（可逆 vs 数据丢失分型）/ 端到端 / 成本耗时。

### 4. 起 API + Dashboard

```bash
python scripts/run_api.py      # http://127.0.0.1:8000
```

接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/patrol` | 触发一次巡检 |
| GET | `/patrols` | 列出巡检记录 |
| GET | `/patrol/{run_id}` | 查询结果（异常/归因/整改/报告） |
| POST | `/patrol/{run_id}/approve` | 高危整改审批（body: `{"decision": {"0": "approved", ...}}`） |
| GET | `/health` | 健康检查 |

### 5. Docker 部署

```bash
docker compose up -d --build
```

## 评估结果（真实 Olist 全量 + DeepSeek + BGE-M3）

| 指标 | 结果 |
|---|---|
| 检测 F1 | 1.0（P/R 满分，4 类异常全检出） |
| 归因正确率 | 0.75（LLM 方差 0.75~1.0） |
| 整改成功率 | 0.50（分型：**可逆 1.0 / 数据丢失 0.0**） |
| 端到端成功率 | 0.50 |
| 单次巡检 | ~39s / ~78 万 tokens |

**整改成功率分型**印证「复检口径」：可逆异常（重复去重、负值修正）SQL 可 100% 修复；数据丢失异常（删行、置空）原始值已毁、需上游重跑，不是 SQL 能修的。

## 项目结构

```
dataquality-agent/
├── src/dataquality_agent/
│   ├── agents/          # LangGraph 节点（inspect/diagnose/remediate/hitl/report/graph）
│   ├── data/            # warehouse / lineage / injector
│   ├── detection/       # L0 rules / L1 stats / runner
│   ├── tools/           # SQL 只读护栏 / 元数据
│   ├── rag/             # embedder / retriever / cases
│   ├── eval/            # metrics / judge / harness
│   ├── observability/   # tracing
│   ├── api/             # FastAPI / runtime / scheduler / wiring
│   ├── llm.py           # DeepSeek 适配（function calling）
│   └── prompts.py       # prompt 集中 + 结构化输出 schema
├── app/                 # 前端 dashboard
├── scripts/             # run_eval.py / run_api.py
└── tests/               # 98 个测试
```

## 测试

```bash
python -m pytest -q
```

# 开源推广落地计划（Open-source rollout）

> 依据：Gemini 建议（`docs/plans/2026-11-21-opensource-policies.md`）× 当前项目进度（v0.3.0 已落地：PostgresAdapter + 声明式 L0 断言，240 测试）。
> 执行模型：**每个任务先由 Gemini 出初稿（内容/文案）→ 我在此基础上对齐项目实际（命名/代码/现状）并落地**。Gemini 出「内容」，我出「机械落地 + 项目对齐」。

## 分档总览

| 档 | 性质 | 内容 |
|---|---|---|
| **Batch 1 — 地基** | 纯写作/配置，零代码，目标无关 | 品牌统一 · 社区三件套 · 模板 · 支持矩阵表 · 头像墙 |
| **Batch 2 — 展示与双语** | 有产出物，1–2 天 | 终端 GIF · README_CN · 文章×2 |
| **Batch 3 — 后置** | 依赖新开发/真实数据/外部贡献者 | benchmark · 新 adapter · 集成 · MCP · 榜单 · 分发 · 反馈闭环 |

## 任务详单

### Batch 1 — 地基（先做，后面所有动作的前置）

**T1 品牌统一**（暂定 `DQAgent`，待用户拍板）
- Gemini 产出：品牌词推荐 + 理由；GitHub About（短/长）；Topics 标签；tagline 微调。
- 我落地：grep `DataAgent` → 新名，改 README（h1/logo alt）、`docusaurus.config.js`（title/navbar/footer）、docs sidebar 标题、GitHub About/Topics。
- 依赖：无。阻塞 T2/T4/T7/T8/T9（它们引用项目名）。

**T2 社区三件套**：`CONTRIBUTING.md`（含新增 Adapter 开发指南，对接 v0.3.0 的 `WarehouseAdapter` 协议 + 声明式断言）+ `CODE_OF_CONDUCT.md` + `SECURITY.md`。
- Gemini 产出：三份草稿。
- 我落地：对齐真实目录/命令（`dqagent` CLI、`pytest`、`[postgres]` extra、四接缝）。

**T3 Issue/PR 模板**：`.github/ISSUE_TEMPLATE/` 三类（新增 Adapter 申请 / 新增 Detector 规则 / 误报漏报 Case）+ PR 模板。
- Gemini 产出：模板文案。
- 我落地：建目录 + 补 YAML frontmatter。

**T4 Adapter 支持矩阵表**（README）。
- Gemini 产出：矩阵表草稿（行=引擎，列=状态/说明）。
- 我落地：以真实状态填（DuckDB ✅ / Postgres ✅ v0.3.0 / 其余 Help Wanted）。

**T5 贡献者头像墙**：`contrib.rocks` / `all-contributors` 一行徽章。
- 我直接落地（无需 Gemini），记一句即可。

### Batch 2 — 展示与双语

**T6 终端动图 GIF**（⏸ 后置，待 ①② 就绪再录）：
- 前置 ①：`run`/`detect` 面向 stdout 的富报告——归因结论 + 证据（探查 SQL / 命中行 / 预期 vs 实际）+ 修复提案 + 审批状态上屏（当前 `run` 只打印 `run_id/status`，画面撑不起来）。
- 前置 ②：真实 demo 数据——全量 Olist + 真实故障模式注入（JOIN 膨胀→主键重复、上游断更→孤儿、脏值→null_rate），替代 3 单 mini 样本。
- 相关硬化：SafeSQL 正则 → sqlglot 真解析（见 ROADMAP 新增项），随 ① 排期。
- 我落地：33 服务器用 vhs 录制 + 嵌 README。

**T7 README_CN.md**（Docusaurus zh-Hans 完整本地化后置）。
- Gemini 产出：README 中文译稿。
- 我落地：与英文版同步、术语对齐。

**T8 文章 A《架构理念篇》**：为什么数据质量 Agent 不能全靠 LLM（Deterministic-First）。
**T9 文章 B《工程安全篇》**：离线克隆验证 + 审批门禁，如何让 AI 参与修复不"删库"。
- Gemini 产出：文章草稿。
- 我落地：对齐真实实现细节（L0/L1/L2、SafeSQL、HITL、离线复检口径），去 AI 味（[[writing-avoid-ai-filler]]）。

### Batch 3 — 后置

T10 benchmark 基准集 · T11 新 adapter 实现（MySQL/ClickHouse/StarRocks/Doris/…）· T12 dbt/Airflow/DolphinScheduler 集成 · T13 MCP Server · T14 榜单收录 · T15 分发（HN/Reddit/Newsletter/掘金·知乎·InfoQ）· T16 反馈闭环/Maintainer。
- 依赖：真实 LLM eval 数据（T10，可走 DeepSeek 闲时）、新开发（T11–T13）、外部贡献者（T16）。逐项在到达前再细化。

## 执行节奏

- 一批一批推进，一个任务一个任务交付；每个任务「Gemini 初稿 → 我适配 → commit（攒够一批或用户要求时 push）」。
- 品牌词是唯一悬而未决的决策（见 T1），其余任务顺序已定。

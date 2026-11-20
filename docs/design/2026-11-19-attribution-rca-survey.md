# 归因层对标调研（Attribution / Root-Cause Analysis Survey）

> 日期：2026-11-19 ｜ 目的：为 diagnose（归因）层的设计提供学术/业界/开源三层对标，找出当前设计的差距与增强点。
> 关联：`docs/specs/2026-11-19-v010-design.md` §7 的四个可插拔接缝之一（归因编排运行时）。

---

## 1. 归因要回答的问题（业界共识）

从"检测到异常"到"解释为什么"，Monte Carlo / Bigeye / Mixpanel / CHRONOS 收敛出同一个闭环，顺序一致：

1. **这个异常是真的吗**（先验真 + 误报抑制）
2. **源头在哪**（血缘溯源，向上游找）
3. **什么变了**（变更关联 + 时间线）
4. **影响多大**（爆炸半径 + 业务关键度）
5. **以前见过吗**（已知根因模式匹配）

---

## 2. 三层对标

### 2.1 学术 —— AIOps 根因定位（Root Cause Localization）

- **两步法**：检测 → 定位（fault localization），与我们"检测 → 归因"对齐。
- **技术家族**（ACM Computing Surveys 10.1145/3736755 等）：
  - 依赖图 + 随机游走 / PageRank 排序（MS-Rank、ServiceRank、Microscope）
  - 因果图发现（时间扰动实验 + 动态 PageRank，如 FaultInsight arXiv 2509.12231；Granger 因果 / PC 算法）
  - 多模态融合（metrics + logs + traces）
- **LLM-Agent 做 RCA 的关键发现**（*Beyond Fault Localization*，arXiv 2608.21310）：
  - 因果链越深、定位越难；"重构故障如何传播"比"识别影响到的服务"更难。
  - **有效归因 = 留在故障影响面 + 用上检索到的证据**；失败归因收敛到少数证据处理错误——**漂移出影响面 / 弃用关键证据 / 浅循环**。
  - → 设计启示：diagnose 必须带"证据面"约束 + 反浅循环护栏。
- **反直觉警示**（*Free to Look, Free to Reason*，arXiv 2610.35767）：**简单 LLM 脚手架可能反超手工多 Agent 编排**。→ 设计启示：归因层的胜负手是"证据检索 + 证据接地"，不是"编排越复杂越好"；避免过度工程化编排。

### 2.2 业界 —— 数据可观测厂商的归因配方

- **Monte Carlo 官方 agent 技能**（`mc-agent-toolkit` 的 "Analyze Root Cause"）：动作序列 = alert lookup → **lineage tracing** → **ETL checks** → **query analysis** → **data profiling** → **匹配已知根因模式 catalog**；用 table/field 级血缘做 **blast radius**。
- **维度归因 / 贡献分解**（Bigeye / Mixpanel / Holistics / StarTree Thirdeye / e6data 都在做）：聚合指标漂移 → **哪个维度 slice 贡献最大**。技术：KL-divergence 惊奇度 + slice 贡献度，StarTree 的 Top Contributors 算法、e6data 的 `impact_score`。这是把"分布漂移"翻译成"哪个 segment 导致"的确定性统计动作，**不依赖 LLM**。
- 五支柱（freshness/volume/distribution/schema/lineage）是**检测面**，归因主要在 **lineage** 这根支柱上展开。

### 2.3 开源同行 —— Agentic DQ 的归因实现

| 项目 | 归因设计 | 可借鉴点 |
|---|---|---|
| **CHRONOS**（LangGraph，10 步） | PRIOR_INV→SCOPE→TEMPORAL→LINEAGE→CODE→DOWNSTREAM→AUDIT→SYNTHESIS→NOTIFY→PERSIST_TRACE；三图（元数据/时序/代码） | **时间线图**（"48h 前什么变了"）、自指记忆、Tier 分级 |
| **Aegis DQ**（库+CLI+Action，6 连接器） | plan→并行校验→LLM diagnose→RCA→SQL remediate→report | 形态与我们最像；差异化在"政策文档→规则生成"；**无 HITL、无 eval 整改成功率** |
| **OpenBlame**（OpenMetadata 上 ReAct） | 血缘 + 爆炸半径 + schema 漂移 diff + 治理 | 调查闭环 = "数据管线的 git blame" |
| **Findata**（A 股数据质量 Agent） | 归因 + **误报抑制** | 合法业务事件（停牌/除权/新股/财报修正）导致的异常不该告警 |
| **dqt**（Agentic BI 数据质量） | 列级血缘 + 因果解释 | 列级血缘做因果链 |

---

## 3. 归因的五个技术动作（提炼）与我们的现状

| 动作 | 回答 | 业界做法 | 我们现状 |
|---|---|---|---|
| ① 血缘溯源 lineage trace | 源头在哪 | Monte Carlo / CHRONOS / OpenBlame | ✅ 有 lineage agent（但血缘是静态注入，非采集） |
| ② 变更关联 change correlation | 什么变了 | Monte Carlo "correlate with timeline"、CHRONOS 时序图 | ⚠️ 缺时间线维度 |
| ③ 维度归因 slice attribution | 哪个 segment 导致 | StarTree / Bigeye / e6data / Mixpanel | ❌ **缺**（L1 检测漂移但不分解到维度） |
| ④ 爆炸半径 blast radius | 影响多大 | Monte Carlo / CHRONOS（Tier 分级） | ⚠️ 血缘有但未形式化下游影响 + 关键度 |
| ⑤ 模式匹配 pattern catalog | 以前见过吗 | Monte Carlo "known patterns" | ⚠️ 有 failure_taxonomy，未与 cases/RAG 显式打通 |

---

## 4. 结论与建议

1. **现有 diagnose 方向正确**：supervisor 分诊（triage）→ lineage/sql/cases 专职 Agent → 聚合，与 Monte Carlo 的 agent 技能、CHRONOS 的 10 步编排一致。
2. **三个明确增强（按 ROI 排序）**：
   - **维度归因（最高 ROI，纯统计、零 LLM 成本）**：L1 检测到分布/体量漂移后，加"slice decomposition"，直接回答"哪个 segment 贡献最大"。技术现成（KL-divergence + contribution，或 PSI 分解到维度）。
   - **变更关联 + 时间线**：把 schema 变更、上游量变、ETL 状态纳入 diagnose 输入（轻量变更日志即可），回答"什么变了"。
   - **爆炸半径 + 关键度分级**：血缘下游遍历 + Tier 分级，作为整改风险分级的证据输入。
3. **护栏（来自 LLM-agent RCA 论文）**：每个归因结论必须**挂到检索到的证据**上（证据面约束）；ReAct 已有 max 步数，补"证据用尽即收"的反浅循环。
4. **护城河仍在**：Aegis DQ（最像我们的同行）**没有 HITL 审批、没有 eval 整改成功率（复检口径）**。归因对标是"补齐技术动作"，不是"放弃差异化"。

---

## 5. 版本安排

- **v0.1.0**：不改归因逻辑（按现有 diagnose 跑通），但把"五个动作 + 证据面护栏"写进 diagnose 的报告结构（作为 specialists 的职责定义）。
- **v0.2.0**（Postgres 连接器 + 数据侧可观测同期）：补**维度归因 + 变更关联 + blast radius 形式化**，并做归因的专项 eval。

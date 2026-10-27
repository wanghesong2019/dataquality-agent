# RAG 案例检索 + 数据飞轮治理设计（收窄落地版）

> 日期：2026-10-27 ｜ 状态：实施中（4.1/4.2/4.3 ✅，4.4/4.5 待做） ｜ 定位：本次改动的唯一决策依据
> 关联文档：`docs/injection-catalog.md`（注入类型目录）、`docs/agent-interview-guide.md`（面试问答）

---

## 1. 背景与范围

数据飞轮（eval → 案例回流 → RAG 增强 → 归因提升）的**写入侧已通**，但**读取侧（RAG 案例检索）有 2 个真 bug + 3 个闭环缺口**；同时 Olist 数据时间轴尾部塌陷使 volume/distribution 检测端到端退化。

本次**只做收窄后的落地范围**，不引入面向流式生产监控的重装备：

| 项 | 内容 | 成本 |
|---|---|---|
| 4.1 | 修 RAG 飞轮 2 个真 bug（id 冲突 / 覆盖降级） | 半小时级 |
| 4.2 | QUERIES 扩到 16 类 + 飞轮案例纳入检索评测 | 一小时级 |
| 4.3 | 检测层修「用错工具」：PSI → chi2（分类列）+ min_count 提档 | 一小时级 |
| 4.4 | 飞轮策展摊平根因类别（补稀有类别注入） | 半小时级 |
| 4.5 | volume/distribution：retention-window 截尾，拿 18/18 | 几行 SQL + 远端重跑 |

**明确不做**（降级为第 5 节「生产化演进方向」的一段话，不实现）：
STL/MSTL 季节性分解、BOCPD 结构突变检测、两级自适应阈值、CUSUM/EWMA、few-shot 合成数据生成、effective-number 检索加权、provenance 三态语料。

> 收窄理由：本项目是**静态 Olist + 一次性批量 eval + 单人 + 简历 demo**，且简历主线是 **Agent 工程**（监督者多 Agent / HITL / 工具调用 / RAG / eval 飞轮），检测统计是输入层支撑。流式监控重装备没有运行载体，硬上只会引来「为什么给静态数据集上 STL+BOCPD」的拷打。

---

## 2. 现状诊断

### 2.1 RAG 案例检索的待办项

| # | 级别 | 问题 | 现状 |
|---|---|---|---|
| 1 | **P0 bug** | 飞轮 id 冲突 | `run_eval.py` 飞轮 id = `{type}_{table}`，`orphan_order_items` 出现 2 次（删 products / 删 sellers）、`null_rate_orders` 出现 2 次（delivered 日期 / customer_id），后者覆盖前者，案例库实际 16 条而非 18 条 |
| 2 | **P0 bug** | 飞轮覆盖静态案例 → 信息降级 | `cases.py::_build_cases` 用 `merged[c["id"]] = c`，飞轮文本只有 `"{table} {column} 异常，根因{category}"`（缺 desc/remedy），覆盖掉静态 6 元组的丰富文本，把案例库喂瘦 |
| 3 | P1 | QUERIES 评测集未跟上扩展 | `QUERIES` 仍是 10 条（对应 10 个静态案例），Tier 1-3 新增 6 类 + 飞轮案例一条没测，检索评测停在「10 案例时代」 |
| 4 | P1 | 飞轮案例未进检索评测 | 只测到「写进去了」，没有「回流后案例能被检索到」的验证，闭环缺失 |
| 5 | P2 | `llm_rerank` 写好了没接线 | `rerank.py::llm_rerank` 有实现有单测，但 `tooling.py::build_cases_tool` 直接 `search(query, k=3)`，无粗筛→rerank；`agent-interview-guide.md` 却写了「已做 BM25 + llm_rerank」 |

### 2.2 三层长尾定性（简表）

| 层 | 长尾在哪 | 本质 | 本次是否处理 |
|---|---|---|---|
| ① 飞轮反馈环 | 案例库只回流「已能注入+检出」的头部类型，尾部冷启动（马太效应） | curation 策略 | ✅ 4.4 |
| ② 检测统计 | Olist 尾部塌陷（最新日 1 单）→ z-score std=0 / PSI min_count 短路 | 小样本退化 | ✅ 4.3 + 4.5 |
| ③ 案例类别 | 根因类别头重脚轻（脏数据注入占 7/16） | 类不均衡 | ✅ 4.4（摊平） |

---

## 3. 业界依据（精炼引用）

| 论点 | 依据 | 用在哪 |
|---|---|---|
| 飞轮长尾要靠「主动策展」而非「被动回收」 | Digital Divide Data：*"production traffic overrepresents common, easy cases and underrepresents the rare, hard ones"*，解法是 curation policy deliberately overweights informative failures + 采边界样本 | 4.4 |
| 飞轮要 MAPE-K 闭环，K 是每轮 enrich 的知识基座 | IBM MAPE-K（2006）+ NVIDIA NVInfo 实践（495 负样本 → 10 真错 → 5000 合成，LLM-as-Judge 77%） | 全文框架 |
| 分类列漂移用 chi2，PSI 只用于数值列 | Evidently 默认选测：小样本分类列→chi2、二值→Z 检验；dqt：*"Categorical columns — use chi_square_drift or cramers_v; PSI requires numeric binning"* | 4.3 |
| PSI 在重尾数据上有 10–20% 基线误报 + 小样本不可靠 | dqt psi.md：*"FPR on heavy-tailed data ~10–20%"*、*"≥200 rows/window、≥5/bin、N<100 噪声"* | 4.3 |
| 自适应阈值会「沸水煮青蛙」吞掉慢漂移 | Boiling Frog Threshold（arXiv 2603.08455）+ 盲点悖论（arXiv 2610.05853） | 第 5 节 |
| 飞轮自投毒 / model collapse，需 provenance + golden dataset | Shumailov model collapse（Nature 2024）、OWASP LLM04 反馈投毒 | 第 5 节 |
| 合成数据在长尾上 mode collapse，恰是最差工具 | Curating the Collapse（AAAI AIES） | 第 5 节 |

> 完整来源见第 7 节。

---

## 4. 实施范围

### 4.1 修 RAG 飞轮 2 个真 bug

**改 1 — 消 id 冲突（`scripts/run_eval.py` 飞轮写入段）**
- 飞轮 id 从 `{type}_{table}` 改为 `{type}_{table}_{column}`（`column` 空则用 `type_table` 兜底；非字母数字替换为 `_`）。
- 效果：`orphan_order_items_product_id` / `orphan_order_items_seller_id`、`null_rate_orders_order_delivered_customer_date` / `null_rate_orders_customer_id` 各自唯一。

**改 2 — 飞轮文本补 desc/remedy（`scripts/run_eval.py` + `rag/cases.py`）**
- 飞轮 `text` 从 `"{table} {column} 异常，根因{category}"` 升级为 `"{table}.{column} {异常描述}，根因{category}，整改{remedy}"`。
- 新增 `REMEDY` 映射（按 `type` → 整改动作，对齐 `injector.py` 的 `ROOT_CAUSE_CATEGORY`），复用静态案例的整改语义：
  - duplicate → 去重 DELETE；orphan → 重跑上游加载；null_rate → 回填；value_range → 回填正确值；lineage_break/freshness → 补跑上游；schema_drift → 回滚 schema；time_inversion → 修正时间字段；future_date → 修正时间戳；volume/distribution → 复查业务口径。

**改 3 — 合并语义（`rag/cases.py::_build_cases`）**
- 修复后飞轮文本不再贫瘠，**「同 id 飞轮覆盖」保留不变**（覆盖不再降级）；因飞轮 id 含 column、静态 id 不含，重叠场景下两者共存（RAG top-3 命中其一即可，优于现状）。

**验收**：飞轮案例 16 条无重复 id；`load_flywheel_cases()` 每条含 desc/remedy + table/column；`run_retrieval_eval.py` 不回归。（✅ 已达成，单测 6/6）

### 4.2 QUERIES 扩到 16 类 + 飞轮纳入检索评测

- `rag/cases.py::QUERIES` 从 10 条扩到覆盖全部 16 个注入类型（补 orphan-sellers、duplicate payments/reviews、value_range review_score/installments/weight、null customer_id、time_inversion、future_date 的 query）。
- `scripts/run_retrieval_eval.py` 增加一步：对 `_build_cases()` 里的**飞轮增量案例**自动生成 query（用其 `type_table_column` 文本），与静态 QUERIES 一起评测，拿到「回流后」的 Recall@3/MRR。

**验收**：`run_retrieval_eval.py` 输出 Recall@3=1.0（MRR≈0.94，近重复案例偶尔排第2），覆盖案例库全部条数。（✅ 已达成：26 条 = 10 静态 + 16 飞轮）

### 4.3 检测层修「用错工具」

- `detection/stats.py::detect_distribution`：把 `psi()` 换成**分类列 chi2**（`order_status` nominal、`review_score` ordinal，二者都非数值列，PSI 用错）。实现用 `scipy.stats.chisquare`（或 chi2_contingency）对「最新窗口分布 vs 基线分布」做独立性检验，p < 0.05 判漂移；`min_count` 从 10 提档到对齐业界口径（ref ≥100 行，不足则显式「样本不足，跳过」而非硬算）。
- `detection/stats.py::detect_volume`：保持现状（不引入 EWMA/CUSUM），仅补 `min_count` 守卫：基线窗口样本不足时显式跳过，不再硬跑 z-score。
- 阈值：不引入自适应，保持硬编码但**在注释中标注**「生产需逐列标定（calibrate_from_history），见第 5 节」。

**验收**：✅ 已达成——检测层重跑 P/R/F1=1.0/1.0/1.0（tp=14 去重键、fp=0、fn=0，16 注入异常全检出）；`detect_distribution` 用 `scipy.stats.chisquare` 拟合优度 + Cochran 合并（expected<5 进 other）；`detect_volume` 补 min_count=100 守卫；单测 17/17（新增 chi2/no-shift/min-count 覆盖）。volume/distribution 在尾部塌陷下均正确跳过（不再误报「量崩」）。

### 4.4 飞轮策展摊平根因类别

- `scripts/run_eval.py::INJECTION_SPECS` 为稀有根因类别各补 1-2 条注入（换表/列/位置，不重复现有）：
  - 「上游任务失败」orphan：再补 1 条 FK 边（如 `payments→orders` 已在 consistency 但可加一条显式注入）；
  - 「上游数据延迟」lineage_break/freshness：补 1 条不同下游表；
  - 「schema变更」：补 1 列。
- 目的：让案例库每类根因 ≥ 2 条，摊平「脏数据注入」的头部优势。

**验收**：`ROOT_CAUSE_CATEGORY` 各根因类别的案例数更均衡；归因准确率对稀有类别不再全错。

### 4.5 volume/distribution：retention-window 截尾

- `data/warehouse.py::build` 的 ODS `orders` 装载处加 cutoff：`WHERE order_purchase_timestamp < '<cutoff>'`，cutoff 取「日单量还没塌陷的最后一天」（需先在 33 服务器查 `daily_metrics` 日单量塌陷点确定精确日期）。
- 下游 DWD/DWS 全靠 orders 派生，join 自然甩掉尾部；其余 16 类检测不受影响。
- 把 volume/distribution 加回 `INJECTION_SPECS`（`inject_volume_spike` / `inject_distribution_drift` 已实现）。

**验收**：重跑 `run_eval.py`，volume/distribution 注入能端到端触发，**18 类型检测 F1=1.0**；文档（本节 + injection-catalog.md 诚实边界一节）注明「运营窗口排除 Olist 2018 采集端塌陷死区，生产仍需 STL 残差检测，见第 5 节」。

---

## 5. 生产化演进方向（只记不做）

> 本节是「如果这是 7×24 流式生产监控，我会怎么扩展」的认知清单，**不在本次落地**。目的是：面试被问「季节性 / 慢漂移 / 飞轮会不会学坏」时，能答出正确方向。

1. **季节性**：volume 监测改 `STL(residual, robust=True)`（日粒度 period=7），只在残差上检测；计数数据先 log 变换；结构突变接 BOCPD，不靠 STL。依据：dqt `stl_residual_zscore`。
2. **慢漂移 / 沸水煮青蛙**：两级架构——L0 规则是非自适应锚点，门控 L1 自适应阈值；自适应只治快异常、保守更新 + 每次变更留痕 + 幅度封顶，绝不吞慢漂移证据。依据：Boiling Frog Threshold、盲点悖论。
3. **飞轮防自投毒**：案例加 provenance 三态（ground-truth / agent-attributed / human-verified），默认只回流 ground-truth（= golden dataset 锚）；非 ground-truth 人工确认或按置信度降权。依据：model collapse、OWASP LLM04。
4. **案例库类不均衡**：万级案例才上 effective-number（Cui β^n）检索加权；当前 18 条 per-class floor 已够。
5. **小样本分类漂移**：chi2 的 expected≥5 守卫，不足时 2×2 走 Fisher exact、大表稀疏走类别合并。
6. **few-shot 合成数据**：仅在真实尾部案例确实拿不到时用，且必须验证（长尾 mode collapse 是硬伤）；优先参数化扰动（真实行 bounded perturb）。
7. **检索精排（llm_rerank 接线）**：`rerank.py::llm_rerank` 已实现待接线；等案例库长大（当前 18 条 top-3 收益边际，且每查一次多一次 LLM 延迟），再把 `tooling.py::build_cases_tool` 改成「粗筛 k=10 → llm_rerank 精排 top-3」。

---

## 6. 实施顺序与验收清单

| 顺序 | 项 | 关键文件 | 验收 |
|---|---|---|---|
| 1 | 4.1 飞轮 bug | `scripts/run_eval.py`、`rag/cases.py`、`scripts/regenerate_flywheel.py`（新） | ✅ 16 条无冲突、含 desc/remedy+table/column（单测 6/6） |
| 2 | 4.2 检索评测 | `rag/cases.py`、`scripts/run_retrieval_eval.py` | ✅ Recall@3=1.0 / MRR=0.942，26 条（10 静态+16 飞轮） |
| 3 | 4.3 检测统计量 | `detection/stats.py`、`tests/test_stats.py` | ✅ 16 类 F1=1.0 不退化，分类列走 chi2 + min_count=100 |
| 4 | 4.4 策展摊平 | `scripts/run_eval.py` | 根因类别案例数均衡 |
| 5 | 4.5 截尾 | `data/warehouse.py`、`scripts/run_eval.py` | 18 类型检测 F1=1.0 |

每步跑通后回写本表验收列，再进下一步。全部完成后同步更新 `injection-catalog.md` 的「诚实边界」一节（指向本「生产演进」第 5 节）。

收尾（零代码）：`agent-interview-guide.md` 的「已做 BM25 + llm_rerank」改为「llm_rerank 已实现待接线」——避免文档与现实不符的露馅风险（对应 2.1 待办 #5）。

---

## 7. 引用

**手动补充资料（本地 `求职管家/手动补充资料/`）**
- `Data Flywheel Strategy…md`（Digital Divide Data，四阶段 flywheel + curation 长尾）
- `Adaptive Data Flywheel…pdf`（NVIDIA NVInfo，MAPE-K + 495 负样本 + 10→5000 合成）
- `psi.md`（dqt，PSI 数值列专用 + 小样本口径 + 重尾 FPR）

**线上**
- dqt `when-not-to-use-dqt.md`：<https://raw.githubusercontent.com/antonbarr-data/dqt/refs/heads/main/docs/when-not-to-use-dqt.md>
- dqt `stl_residual_zscore.md`：<https://github.com/antonbarr-data/dqt/blob/main/docs/algorithms/stl_residual_zscore.md>
- Evidently `data-drift-algorithm`：<https://docs-old.evidentlyai.com/reference/data-drift-algorithm>
- AutoDQ（自适应 DQ + 误报率）：<https://zenodo.org/records/21262974/files/NathanML.pdf>
- Boiling Frog Threshold：<https://browse-export.arxiv.org/abs/2603.08455>
- 盲点悖论（自适应吞检测信号）：<https://export.arxiv.org/pdf/2610.05853>
- Model collapse（Nature 2024 转述）：<https://proddr.informationweek.com/machine-learning-ai/a-silent-erosion-of-enterprise-ai-by-data-poisoning>
- OWASP LLM04 反馈投毒：<https://link.springer.com/content/pdf/10.1007/s10462-026-11590-x.pdf>
- Curating the Collapse（合成数据 mode collapse）：<https://ojs.aaai.org/index.php/AIES/article/view/43319>
- Class-Balanced Loss（Cui 2019，effective number）：<https://openaccess.thecvf.com/content_CVPR_2019/html/Cui_Class-Balanced_Loss_Based_on_Effective_Number_of_Samples_CVPR_2019_paper.html>

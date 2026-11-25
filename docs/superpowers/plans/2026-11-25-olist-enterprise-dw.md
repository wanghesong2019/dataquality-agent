# Olist 企业级数仓（DuckDB）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从全量 Olist 重建一套方法论正确的 4 层数仓（ODS→DWD→DIM→DWS→ADS），并让 DQAgent 在上面跑通 `detect`/`run` 作为掘金展 demo。

**Architecture:** 升级 `Warehouse.build()`（现有 ODS→DWD→DWS 骨架）补 DIM 维度层 + ADS 应用层；扩展声明式断言目录 + 注入器覆盖新维度表与真实故障；产出数仓设计文档 + 终端 demo。stretch：dashboard 渲染可观测性。

**Tech Stack:** DuckDB（参考适配器）、现有 `Warehouse`/`Injector`/`catalog`/`rules` 模块。

**Spec:** `docs/superpowers/specs/2026-11-25-olist-enterprise-dw-design.md`

## Global Constraints

- DuckDB only；Postgres 后置（demo 全流程通了再做）。
- 全量 Olist 在 33 服务器构建；不要本地跑（[[connect-33-server]]）。
- demo 规模；不引入 Hadoop/Flink/实时。
- 不破坏现有 240 测试：`Warehouse.build()` 的 ODS→DWD→DWS 行为向后兼容（现有表名/列名不变，只新增 dim_*/ads_*）。
- 命名规范：`dwd_` 事实/明细、`dim_` 维度、`dws_` 汇总、`ads_` 应用。

## Review Focus

1. **孤儿维度行**：orders 截尾 + 子表清理后，`dim_customer`/`dim_seller` 会残留「无对应事实」的维度行——维度表允许慢变化，断言不能把它们判成错误。
2. **geolocation 去重口径**：`dim_geolocation` 一邮编一城市后，事实表仍按原始 zip 关联；JOIN 后城市唯一性不能再触发 `zip_inconsistency` 误报。
3. **ADS 宽表 JOIN 膨胀**：`order_wide = items ⋈ products ⋈ sellers`，若某 product_id/seller_id 关联多行会膨胀——膨胀率检测要覆盖它，且注入器别污染 `amount_mismatch`。
4. **注入 JOIN 膨胀的连带误报**：改主键/价格会连带触发其它检测（amount_mismatch/state_conflict）——注入计划要像 value_range 避开 `price` 那样避开污染。
5. **dim_date 覆盖率**：NULL/空 `purchase_timestamp` 的订单落不进 dim_date——ADS 用 LEFT JOIN 兜住，不留悬空 date_key。

---

### Task 1: dim_date 日期维度表

**Files:**
- Modify: `src/dataquality_agent/data/warehouse.py`
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Produces: `build()` 后存在 `dim_date(date_key DATE, year INT, quarter INT, month INT, week INT, day_of_week INT)`，date_key 覆盖所有 distinct 下单日期。

- [ ] **Step 1: 写失败测试** `test_dim_date_covers_all_order_dates`：`SELECT COUNT(*) FROM dim_date` == `SELECT COUNT(DISTINCT CAST(order_purchase_timestamp AS DATE)) FROM dwd_orders`；另 `test_dim_date_columns_typed`：`date_key` 是 DATE、`year`/`month` 是 INTEGER。
- [ ] **Step 2: 跑测试确认失败**（`dim_date` 不存在 → Binder Error）
- [ ] **Step 3: 实现** — `build()` 在 DWD 之后加：`CREATE OR REPLACE TABLE dim_date AS SELECT DISTINCT CAST(order_purchase_timestamp AS DATE) AS date_key, EXTRACT(year...) AS year, ... FROM dwd_orders`。
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: commit** `feat(dw): add dim_date dimension table`

### Task 2: 其余维度表（customer/seller/product/geolocation/category）

**Files:**
- Modify: `src/dataquality_agent/data/warehouse.py`
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Produces: `dim_customer(customer_id PK)`, `dim_seller(seller_id PK)`, `dim_product(product_id PK)`, `dim_geolocation(zip_prefix PK, one row per zip)`, `dim_category(category_name PK)`。

- [ ] **Step 1: 写失败测试** `test_dim_tables_unique_pk`：每张 dim 表 `COUNT(*) == COUNT(DISTINCT pk)`；`test_dim_geolocation_one_row_per_zip`：`COUNT(*) == COUNT(DISTINCT zip_prefix)`。覆盖 Review Focus 2。
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现** — 从现有 `dwd_customers`/`dwd_sellers`/`dwd_products`/`dwd_geolocation`/`product_category_translation` 抽 `dim_*`（geolocation 按 zip 去重取众数城市）。
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: commit** `feat(dw): add dim_customer/seller/product/geolocation/category`

### Task 3: ADS 应用层（order_wide + gmv_daily_board + seller_daily_cube）

**Files:**
- Modify: `src/dataquality_agent/data/warehouse.py`
- Test: `tests/test_warehouse.py`

**Interfaces:**
- Produces: `ads_order_wide`（items ⋈ orders ⋈ dim_product ⋈ dim_seller ⋈ dim_customer 的宽表）、`ads_gmv_daily_board`（date × gmv × orders × aov）、`ads_seller_daily_cube`（seller × date 聚合）。

- [ ] **Step 1: 写失败测试** `test_order_wide_no_fanout`：`ads_order_wide` 行数 == `order_items` 行数（覆盖 Review Focus 3）；`test_gmv_daily_board_matches_daily_metrics`：`ads_gmv_daily_board` 的 gmv/orders 与 `daily_metrics` 一致。
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现** — 用 LEFT JOIN 组装宽表（维度键用 dim_* 主键），日期用 `dim_date` LEFT JOIN 兜住（覆盖 Review Focus 5）。
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: commit** `feat(dw): add ADS layer (order_wide + gmv board + seller cube)`

### Task 4: 指标体系口径文档

**Files:**
- Create: `docs/data-warehouse/metrics.md`

**Interfaces:** 无代码接口；产出指标口径文档（原子指标 + 派生指标 + 计算逻辑 + 时间/去重口径）。

- [ ] **Step 1: 写文档** — GMV、订单量、支付额、评价分为原子指标；客单价、复购率、履约时效、支付转化率为派生指标；每条含定义 + 计算 SQL + 口径。
- [ ] **Step 2: 自检** — 每个指标能对应到 `dws_`/`ads_` 里的一张表或一条 SQL（不写代码里没有的口径）。
- [ ] **Step 3: commit** `docs(dw): metric dictionary with 口径`

### Task 5: 断言目录覆盖维度表

**Files:**
- Modify: `src/dataquality_agent/detection/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Produces: `default_assertions` 增补 `dim_*` 主键唯一 + 事实→维度参照完整性。

- [ ] **Step 1: 写失败测试** `test_dim_assertions_pass_clean`（干净数仓上 dim 断言无异常）、`test_dim_duplicate_detected`（注入 dim 主键重复 → 检出）。覆盖 Review Focus 1（孤儿维度不误报）。
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现** — 加 `unique`（dim 主键）+ `referential`（order_items→dim_product、order_items→dim_seller、orders→dim_customer）。
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: commit** `feat(detection): assertions for dim tables`

### Task 6: 注入器扩展真实故障

**Files:**
- Modify: `src/dataquality_agent/data/injector.py`、`src/dataquality_agent/data/demo.py`
- Test: `tests/test_injector.py`、`tests/test_demo_data.py`

**Interfaces:**
- Produces: 注入计划新增「JOIN 膨胀」「上游断更」两类，注入后检测 F1 仍 == 1.0。

- [ ] **Step 1: 写失败测试** `test_join_fanout_detected`（重复某 seller 行 → order_items⋈sellers 膨胀 → 检出主键重复）、`test_upstream_break_detected`（删某日数据 → 血缘断裂检出）。覆盖 Review Focus 4（注入不污染 amount_mismatch）。
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现** — 加 `inject_join_fanout`（复制 seller 行）、`inject_upstream_break`（删某分区）；沿用「避开 price」的污染规避原则。
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: commit** `feat(injector): JOIN fan-out + upstream-break faults`

### Task 7: demo 数据生成 + 掘金录屏

**Files:**
- Modify: `scripts/make_demo_data.py`、`scripts/demo.tape`
- Verify: 33 服务器跑通，产出 `assets/demo.gif`

- [ ] **Step 1: 扩展 `make_demo_data.py`** — 全量 Olist 建仓 + 注入（含 Task 6 新故障）+ 生成 demo 目录。
- [ ] **Step 2: 33 服务器跑** — `dqagent detect` + `dqagent run` 全流程跑通（[[connect-33-server]]，不在本地跑）。
- [ ] **Step 3: 录屏** — 用 [[record-terminal-gif]] skill 重录 `detect` + `run`（新数仓 + 新注入画面）。
- [ ] **Step 4: 拉回 `assets/demo.gif`，嵌 README + 文档首页**
- [ ] **Step 5: commit** `docs(demo): re-record demo GIF on full Olist warehouse`

### Task 8: 数仓设计文档 + 简历精炼版

**Files:**
- Create: `docs/data-warehouse/design.md`（维度建模 + 分层 + 治理）、`docs/data-warehouse/resume.md`（面试/简历精炼版）

- [ ] **Step 1: 写 `design.md`** — 分层规范、星型模型、维度/事实清单、治理规范（对齐 spec）。
- [ ] **Step 2: 写 `resume.md`** — 面向面试的「STAR 化」精炼版（背景/分层/建模/指标/治理/质量闭环，可量化）。
- [ ] **Step 3: commit** `docs(dw): warehouse design + resume-ready writeup`

### Task 9 (stretch): dashboard + 可观测性

**Files:**
- Modify: `src/dataquality_agent/api/runtime.py`、`src/dataquality_agent/api/main.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Produces: `/patrol/{run_id}` 响应新增 `trace`（步骤级 span 树）+ `cost`（成本台账）。

- [ ] **Step 1: 写失败测试** `test_api_returns_trace_and_cost`：`get(run_id)` 返回含 `trace`（含 span 名 + 耗时 + token）与 `cost`。
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现** — `PatrolRuntime` 持有 `Tracer`，`trigger/get` 把 `tracer.render_tree()`/`summary_by_name()`/`total_cost()` 序列化进响应。
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: commit** `feat(api): expose step-level trace + cost in patrol response`

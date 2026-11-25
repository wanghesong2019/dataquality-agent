# Olist 企业级数仓设计文档

> 基于全量 Olist（~10 万订单）在 DuckDB 上搭建的方法论正确、demo 规模的企业级数仓。
> 对齐数据开发 JD 的四项硬要求：**数据分层、维度建模、指标体系、数据治理**。

## 1. 分层架构（ODS → DWD → DIM → DWS → ADS）

| 层 | 职责 | 关键设计 | 表 |
|---|---|---|---|
| **ODS**（贴源层） | 原始 CSV 原样落库，保留脏数据作为证据 | `orders` 按采集截尾（2018-08-24），子表清悬空 `order_id` | 9 张原始表 |
| **DWD**（明细层） | 类型规范化，脏值 → NULL | `TRY_CAST`：加载层健壮、检测层严格（分层职责分离） | `dwd_orders` / `dwd_order_items` / `dwd_payments` / `dwd_reviews` + 维度原料 |
| **DIM**（维度层） | 规范维度表：显式主键 + 去重 | `dim_geolocation` 一邮编一行（取众数城市，消除 zip→多城市矛盾） | `dim_date` / `dim_customer` / `dim_seller` / `dim_product` / `dim_geolocation` / `dim_category` |
| **DWS**（汇总层） | 按主题域轻度聚合（多基线） | 供 L1 统计检测（volume/distribution 基线） | `daily_metrics` / `seller_metrics` / `category_metrics` / `payment_summary` |
| **ADS**（应用层） | 面向业务的宽表/看板/CUBE | 宽表 JOIN 维度不膨胀（一行一 `order_item`） | `ads_order_wide` / `ads_gmv_daily_board` / `ads_seller_daily_cube` |

## 2. 维度建模（星型模型）

**事实表**（含度量）：
- `dwd_orders`（订单事实）：4 个时间戳，`order_status`
- `dwd_order_items`（明细事实）：`price` / `freight_value`
- `dwd_payments`（支付事实）：`payment_value` / `payment_installments`
- `dwd_reviews`（评价事实）：`review_score`

**维度表**（含属性）：
- `dim_date`：从 `order_purchase_timestamp` 拆 `year/quarter/month/week/day_of_week`
- `dim_customer` / `dim_seller` / `dim_product` / `dim_geolocation` / `dim_category`

**关系**：`order_items` ⋈ `dim_product`（product_id）、⋈ `dim_seller`（seller_id）；`orders` ⋈ `dim_customer`（customer_id）、⋈ `dim_date`（date）；`dim_customer`/`dim_seller` 经 zip 关联 `dim_geolocation`。

## 3. 指标体系

见 [metrics.md](./metrics.md)：原子指标（GMV/订单量/支付额/评价分）+ 派生指标（客单价/复购率/履约时效/支付转化率），每条含定义/计算逻辑/口径/来源。

## 4. 数据治理

- **命名规范**：`dwd_` 事实/明细、`dim_` 维度、`dws_` 汇总、`ads_` 应用。
- **数据标准**：日期 → TIMESTAMP、金额/经纬度/重量 → DOUBLE、空串 → NULL（DWD `TRY_CAST`）。
- **质量规则**（声明式 L0 断言目录，YAML → Detector）：
  - 主键唯一（`unique`）：事实表 + 维度表 + ODS 维度表（`sellers`/`products`/`customers`，JOIN 膨胀的根因）。
  - 参照完整性（`referential`）：星型模型 FK 网。
  - 值域（`value_range`）/ 空值（`null_rate` / `not_null`）。
  - 跨表一致性（公式型）：金额对账 / 状态矛盾 / 邮编一致。

## 5. 建仓流程

`Warehouse.build()`：读 9 张 CSV → ODS 落库 + 截尾 → DWD 规范化 → DIM 抽取去重 → DWS 聚合 → ADS 宽表/看板。全程 `CREATE OR REPLACE TABLE`，幂等可重跑；eval 用 `clone_warehouse`（DuckDB EXPORT/IMPORT）在一次性副本上注入、不污染干净数仓。

## 6. 与 DQAgent 的集成

DQAgent 的 `WarehouseAdapter`（4 个只读原语）读取本数仓；`detect` 跑 L0 断言 + L1 统计，`run` 叠加 L2 语义 + 薄归因 + 整改 + HITL 审批。demo 在数仓注入 5 类真实故障（主键重复 / JOIN 膨胀根因 / 孤儿 / 空值 / 负值），`detect` 秒级全检出，`run` 全链闭环。

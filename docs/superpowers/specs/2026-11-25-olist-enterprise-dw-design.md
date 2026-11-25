# Olist 企业级数仓（方法论正确 · demo 规模）设计文档

> 依据：掘金作品展（12/10 截止，需现场可交互 demo）× 数据开发 JD 的数仓硬技能要求。
> 定位：一套「方法论正确、demo 规模」的企业级数仓，作为 DQAgent 的舞台 + 数仓技能的简历实料。

## Intent & Why

两个目标，一套交付：

1. **掘金展 demo**：DQAgent 需要一个可信的「企业级数仓」来现场演示「巡检 → 归因 → 整改 → 审批」。
2. **对标 JD**：数据开发 JD 的数仓硬要求收敛成一套——维度建模、数据分层（ODS/DWD/DWS/ADS）、指标体系、数据治理。这套方法论与具体域/引擎无关，做对了就能写进简历、经得起面试拷打。

选 **Olist 电商**：全量数据已可得（33 服务器，~10万订单、9 张表、真实脏数据），维度建模教科书级契合，且电商是目标 JD 里出现频率最高的域。

## Goals

1. 从全量 Olist 重建一套 **4 层数仓**：ODS → DWD → DWS → ADS（现有代码只有 ODS→DWD→DWS，缺 ADS）。
2. 规范 **维度建模**：星型模型——事实表 + 规范化维度表（`dim_date`/`dim_customer`/`dim_seller`/`dim_product`/`dim_geolocation`）。
3. 沉淀 **指标体系**：原子指标 + 派生指标 + 口径定义（GMV、客单价、复购率、履约时效、评分等）。
4. **数据治理**：分层命名规范 + 数据类型标准 + DQAgent 质量规则目录（真实脏数据 + 注入故障）。
5. **掘金 demo**：`dqagent detect` / `dqagent run` 在这套数仓上跑通，可现场交互。

## Non-goals / Anti-goals

- 不做 Hadoop/Spark/Flink/实时数仓/海量数据（已定 demo 规模）。
- 不做生产部署 / 多租户 / 权限体系（演示够用即可）。
- 不虚标「大数据调优」能力（诚实对齐 [[dont-inflate-bigdata-background]]：重心是数仓**方法论**，不是**规模**）。

## Constraints

- **引擎**：DuckDB（DQAgent 参考适配器；`Warehouse.build()` 已走 DuckDB，零迁移）。
- **数据**：全量 Olist，33 服务器 `/data/home/hermes/olist`（121MB，9 张 CSV）。
- **时间**：掘金 12/10 截止。
- **位置**：DQAgent 仓库内，升级现有 demo 建仓路径（`data/warehouse.py` / `data/demo.py`），不单开 repo。

## Approaches

- **选定**：Olist 电商，从原始 ODS 重建完整 4 层 + 规范维度建模 + 指标体系 + DQAgent 监控。
- **被否**：
  - 供应链/财务复用 Olist 换口径——数据可得性不变但故事线牵强；
  - 真·大数据栈（Doris/StarRocks/Flink）——规模/风险不匹配 demo，且与「不虚标大数据」矛盾。

## Design

### 1. 分层（在现有骨架上补全）

```
ODS（原始贴源层）：9 张 CSV 原样落库，保留原始脏数据作为证据；
  orders 按 2018-08-24 截尾（采集塌陷死区），子表跟着清理悬空 order_id。
DWD（明细层）：TRY_CAST 类型规范化，脏值→NULL（加载层健壮、检测层严格）；
  事实表 dwd_orders / dwd_order_items / dwd_payments / dwd_reviews；
  维度原料 dwd_products / dwd_sellers / dwd_customers / dwd_geolocation。
DIM（维度层，规范建模）：从 DWD 维度原料抽取，规范命名 + 显式主键 + 去重；
  dim_date（从 order_purchase_timestamp 拆 year/quarter/month/week/day）、
  dim_customer / dim_seller / dim_product / dim_geolocation / dim_category。
DWS（汇总层）：按主题域聚合——daily_metrics / seller_metrics / category_metrics /
  payment_summary（现有 4 张，补全 + 对齐 dim 主键）。
ADS（应用层，新增）：面向业务的宽表/CUBE——如 order_wide（订单大宽表）、
  seller_daily_cube、gmv_daily_board（大屏指标）。
```

### 2. 维度建模（星型）

| 表 | 类型 | 键 | 度量/属性 |
|---|---|---|---|
| `dwd_orders` | 事实（事件） | order_id | order_status, 4 个时间戳 |
| `dwd_order_items` | 事实（明细） | order_id + order_item_id | price, freight_value |
| `dwd_payments` | 事实（支付） | order_id + payment_sequential | payment_value, installments, type |
| `dwd_reviews` | 事实（评价） | review_id | review_score |
| `dim_date` | 维度 | date_key | year/quarter/month/week/day |
| `dim_customer` | 维度 | customer_id | unique_id, city, state, zip |
| `dim_seller` | 维度 | seller_id | city, state, zip |
| `dim_product` | 维度 | product_id | category, weight, 尺寸 |
| `dim_geolocation` | 维度 | zip_prefix | lat/lng, city, state |

关系：`order_items` 关联 `dim_product`/`dim_seller`；`orders` 关联 `dim_customer`/`dim_date`；`dim_customer` 经 zip 关联 `dim_geolocation`。

### 3. 指标体系（口径沉淀）

- **原子指标**：GMV、订单量、支付额、评价分。
- **派生指标**：客单价（GMV/订单量）、复购率、履约时效（送达−下单）、支付转化率。
- **口径文档**：每个指标写清定义 + 计算逻辑 + 时间口径（T-1/自然日）+ 去重口径（按 order_id 去重）。

### 4. 数据治理

- **命名规范**：`ods_`（或原样）/ `dwd_` / `dim_` / `dws_` / `ads_` 前缀，事实/维度/汇总/应用各归其位。
- **数据标准**：日期→TIMESTAMP、金额/经纬度/重量→DOUBLE/数值、空串→NULL。
- **质量规则**：DQAgent 声明式 L0 断言目录覆盖 dim 主键唯一、事实↔维度参照完整性、跨表一致性（金额对账/状态矛盾/邮编一致）+ 真实脏数据 + 注入故障。

### 5. DQAgent 集成

- `Warehouse.build()` 扩展出完整 ODS→DWD→DIM→DWS→ADS。
- `default_assertions` 覆盖新维度表（dim 主键 + 参照 + 跨表）。
- 注入器对全量 Olist 注入真实故障（JOIN 膨胀→主键重复→GMV 翻倍、孤儿外键、上游断更→血缘断裂、脏值→空值率）。
- 掘金 demo：`detect` + `run` 终端演示（复用 [[record-terminal-gif]] 录屏 skill）；`dqagent serve` dashboard 作为现场交互加分项（可选项，可把可观测性——步骤级 trace + 成本台账——渲染进去，见 Deliverables 5）。

## Deliverables

1. **数仓代码**：`data/warehouse.py` 补全 4 层 + 维度表 + ADS。
2. **数仓设计文档**：维度建模 + 分层规范 + 指标体系（这份文档 + 一份面向面试/简历的精炼版）。
3. **DQAgent 监控**：声明式断言目录 + 注入器 + demo 数据生成脚本。
4. **掘金 demo**：终端演示（detect+run）+ 作品页内容。
5. **（stretch）dashboard + 可观测性**：把 `Tracer` 步骤级 trace 树 + 成本台账接到 `/patrol/{run_id}` 响应 + 前端渲染（ROADMAP v1.0）。

## What's left to the builder

- 各层 DDL / ETL SQL、维度表抽取逻辑（含去重 + 主键）、指标计算 SQL。
- 注入器扩展到全量 Olist 的故障注入计划。
- 数仓设计文档的面试/简历精炼版。

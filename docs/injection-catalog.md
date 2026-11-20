# 异常注入类型扩展目录（数据飞轮燃料）

> 目的：把 eval 的注入类型从 4 类扩到 ~24 类，覆盖 Olist 的 7 个异常维度，为「数据飞轮」（案例库回流）提供多样性燃料，同时补上「检测 F1 只指 L0」的诚实边界。
> 日期：2026-10-26 ｜ 状态：设计完成，按 Tier 1→2→3→4 实施中

---

## 设计原则

1. 每个注入类型对应一个**真实的 Olist 数据质量约束**（不硬造）。
2. 覆盖不同表、不同异常维度（完整性/唯一性/值域/一致性/时间/分布/血缘）。
3. 每个注入有 **ground-truth 根因**（对齐 `Diagnosis.root_cause_category` 枚举）。
4. 避开真实数据自带脏点（products 610 空 category、payment_type not_defined、canceled 订单交付日期本就空）。

## 注入类型目录（24 类，7 维度）

### A. 完整性（null）· 4 类 → 根因「脏数据注入」
| # | 表.列 | 注入动作 |
|---|---|---|
| 1 | orders.order_delivered_customer_date | delivered 订单置空 |
| 2 | orders.customer_id | 关键外键置空 |
| 3 | products.product_category_name | 品类置空（避开已空的 610） |
| 4 | reviews.review_score | 评分置空 |

### B. 唯一性（duplicate）· 4 类 → 「脏数据注入」
| # | 表.键 |
|---|---|
| 5 | orders.order_id |
| 6 | order_items(order_id + order_item_id) 复合键 |
| 7 | payments(order_id + payment_sequential) 复合键 |
| 8 | reviews.review_id |

### C. 值域（value_range）· 5 类 → 「脏数据注入」
| # | 表.列 | 注入动作 |
|---|---|---|
| 9 | order_items.price | 负值 |
| 10 | order_items.freight_value | 负值 |
| 11 | reviews.review_score | 6 或 0（非法评分） |
| 12 | payments.payment_installments | 0 或 >24 |
| 13 | products.product_weight_g | 负值/0 |

### D. 一致性（跨表/逻辑）· 5 类
| # | 表 | 注入动作 | 根因 |
|---|---|---|---|
| 14 | order_items→products | 删 products | 上游任务失败 |
| 15 | order_items→sellers | 删 sellers | 上游任务失败 |
| 16 | payments vs order_items | 金额不符 | ETL 逻辑变更 |
| 17 | orders.status vs 交付日期 | 状态矛盾 | ETL 逻辑变更 |
| 18 | orders.delivered < purchase | 时间倒挂 | ETL 逻辑变更 |

### E. 时间/新鲜度 · 2 类
| # | 表.列 | 注入动作 | 根因 |
|---|---|---|---|
| 19 | 表水位线 | 落后当前日期 | 上游数据延迟 |
| 20 | orders.order_purchase_timestamp | 设为 2020（超范围） | 脏数据注入 |

### F. 分布/统计（L1）· 2 类
| # | 表.列 | 注入动作 | 根因 |
|---|---|---|---|
| 21 | orders.order_status | 某天 canceled 比例突增 | 数据倾斜 |
| 22 | daily_metrics.orders | 某天订单量突刺 | 业务真实波动 |

### G. schema / 血缘（L1）· 2 类
| # | 表 | 注入动作 | 根因 |
|---|---|---|---|
| 23 | 某表 | 删列/改类型 | schema 变更 |
| 24 | daily_metrics vs orders | 水位线落后 | 上游数据延迟 |

---

## 工作分层（实施顺序）

| Tier | 类型 | 成本 | 说明 |
|---|---|---|---|
| **1** | #15 orphan(sellers) + #24 lineage_break + #23 schema_drift（已支持，加进 INJECTION_SPECS） | 零成本 | injector 已有方法；#16/17 cross-table 是 always-on（注入 F1 平凡，跳过）；#19 freshness 与 lineage_break 干扰（单独测） |
| **2** | #2/3/4/6/7/8/10/11/12/13（扩 injector 变体） | 半天 | 扩到更多表/列 |
| **3** | #18 时间倒挂、#20 未来日期（新 L0 规则 + 注入） | 半天 | 需新检测规则 |
| **4** | #21 distribution、#22 volume（新 L1 注入方法） | 半天 | 检测已有，注入方法待写 |

> 注：Tier 1 里的 #15（删 sellers）也属"injector 已有方法"（orphan 通用），可一并进。

## 实施记录（TDD）

- [x] **Tier 1**：INJECTION_SPECS 扩到 7 类（orphan-sellers + lineage_break + schema_drift）
  - 结果（修复语义重叠后）：检测 P=1.0 / R=1.0 / F1=1.0（8 类型：7 注入 + freshness 重叠标注）
  - **lineage_break=1.0、schema_drift=1.0、freshness=1.0（L1 全覆盖）**；L0 四类也全 1.0
  - 归因 0.75（8 类型，归因错 2）、整改 0.286（schema/lineage 不可逆）、token 25万
  - ✅ 修复：lineage_break 注入连带触发 freshness（删下游 → 同时"落后上游"+"落后当前"）→ 修 ground-truth（injector 同时标注 freshness anomaly），P 从 0.857 → 1.0，174 测试全绿
  - 发现：L1 根因（上游延迟/schema 变更）比"脏数据注入"更难归因
- [x] **Tier 2**：扩 duplicate(payments/reviews) + value_range(review_score/installments/weight) + null(customer_id)
  - 结果（修复 orphan 口径后）：检测 P=1.0 / R=1.0 / F1=1.0（14 类型全 F1=1.0）
  - 归因 0.857、整改 0.583、端到端 0.5、token 35万
  - ✅ 修复：null customer_id 注入触发 orders→customers 孤儿（NULL 外键被当 orphan）→ check_orphan 加 `IS NOT NULL`，orphan F1 从 0.667 → 1.0
  - 发现：Tier 2 的 duplicate/value_range/null 是"脏数据注入"（比 L1 更易归因+更可逆），把归因(0.75→0.857)和整改(0.286→0.583)都拉高了
- [x] **Tier 3**：时间倒挂 + 未来日期（新 L0 规则 `check_time_inversion`/`check_future_date` + 新注入方法）
  - 结果：检测 P=1.0 / R=1.0 / F1=1.0（16 类型全 F1=1.0）
  - 归因 0.75（16 类型，归因错 4）、整改 0.571（time_inversion 可逆，数据丢失成功 0.0→0.143）、端到端 0.438
  - 发现：时间倒挂/未来日期根因（ETL逻辑变更/脏数据注入）从症状看都是"数据错了"，比纯脏数据更难归因，归因 0.857→0.75
- [x] **Tier 4**：volume/distribution 注入方法 + retention-window 截尾（warehouse.py 把 orders 截到 2018-08-24 前，甩掉采集端塌陷死区）→ volume/distribution 端到端触发。检测 21 条注入 F1=1.0。诚实边界：运营窗口排除采集端塌陷死区，生产仍需 STL 残差检测。
- [x] 数据飞轮：eval 结果 → cases 库回流（21 条飞轮案例，每类根因 ≥2）

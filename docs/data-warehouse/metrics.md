# Olist 数仓指标体系（口径字典）

> 对齐数据开发 JD 的「指标体系 / 口径沉淀」要求。每个指标写清**定义 / 计算逻辑 / 口径 / 数据来源**，不写代码里没有的口径。
> 分层约定：原子指标落 DWS，派生指标由原子指标组合或从 DWD 计算，业务看板落 ADS。

## 一、原子指标

| 指标 | 定义 | 计算逻辑 | 口径 | 来源表 |
|---|---|---|---|---|
| **GMV**（成交额） | 下单商品成交金额（不含运费） | `SUM(order_items.price)` | 自然日；**含取消订单**（当前未剔除 `canceled`） | `daily_metrics.gmv` · `seller_metrics.gmv` · `category_metrics.gmv` · `ads_gmv_daily_board.gmv` |
| **订单量** | 下单订单数 | `COUNT(DISTINCT order_id)` | 自然日 | `daily_metrics.orders` |
| **支付额** | 支付总金额 | `SUM(payment_value)` | 按支付方式分组 | `payment_summary.total_value` |
| **评价分** | 订单评价平均分 | `AVG(review_score)` | 按卖家（关联订单评价） | `seller_metrics.avg_score` |

## 二、派生指标

| 指标 | 定义 | 计算逻辑 | 口径 | 来源 |
|---|---|---|---|---|
| **客单价（AOV）** | 平均每单成交额 | `GMV / 订单量` | 自然日；分母 = 去重订单数 | `daily_metrics.avg_order_value` |
| **复购率** | 有 ≥2 单的客户占比 | `有 ≥2 单的 customer_unique_id 数 / 总 customer_unique_id 数` | 全时段窗口 | 从 `dwd_orders ⋈ dim_customer` 派生（见下方 SQL） |
| **履约时效** | 下单到送达的平均天数 | `AVG(delivered - purchase)` | 仅 `delivered` 订单 | 从 `dwd_orders` 派生 |
| **支付转化率** | 已支付订单占比 | `COUNT(DISTINCT payments.order_id) / COUNT(DISTINCT orders.order_id)` | 自然日 | 从 `dwd_orders` + `dwd_payments` 派生 |

### 复购率派生 SQL（口径示例）

```sql
SELECT
  COUNT(DISTINCT CASE WHEN t.cnt >= 2 THEN c.customer_unique_id END) * 1.0
    / NULLIF(COUNT(DISTINCT c.customer_unique_id), 0) AS repeat_purchase_rate
FROM (SELECT customer_id, COUNT(DISTINCT order_id) AS cnt FROM dwd_orders GROUP BY customer_id) t
JOIN dim_customer c ON t.customer_id = c.customer_id
```

## 三、口径决策记录

- **GMV 含取消订单**：当前简化，未剔除 `canceled`；生产应区分「下单 GMV」与「成交 GMV（剔除取消）」，这是一个明确的口径分叉点。
- **客单价分母**：用去重订单数（一单多商品时，GMV 是明细求和、分母是订单数），避免把明细条数当订单数。
- **评价分重复计分**：`seller_metrics` 里一单多 seller 时评分重复计入，检测导向可接受（已注释）。
- **复购按 `customer_unique_id` 而非 `customer_id`**：Olist 一人可多 `customer_id`，复购语义是「同一人多次下单」，故用 `customer_unique_id`。

## 四、分层映射

| 粒度 | 表 | 说明 |
|---|---|---|
| 日 | `daily_metrics` | 日单量 / GMV / 客单价 |
| 卖家 | `seller_metrics` | 卖家单量 / GMV / 平均分 |
| 品类 | `category_metrics` | 品类单量 / GMV / 商品数 |
| 支付方式 | `payment_summary` | 支付笔数 / 总额 / 平均分期 |
| 日看板（ADS） | `ads_gmv_daily_board` | 日 GMV 看板 + 日期维度（year/quarter/month） |
| 卖家×日（ADS） | `ads_seller_daily_cube` | 卖家×日立方体 |
| 订单宽表（ADS） | `ads_order_wide` | 一单一明细 + 品类/卖家/客户维度 |

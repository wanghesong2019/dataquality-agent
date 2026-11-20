"""L0 规则断言检测：确定性、0 LLM、最可解释。"""
from dataquality_agent.models import Anomaly, Evidence


def sample_offending(adapter, table: str, where_sql: str, limit: int = 20) -> list[dict]:
    """采样命中行：SELECT * FROM {table} WHERE {where_sql} LIMIT {limit}，列名对齐返回 list[dict]。

    证据采集的核心：判定 fail 时顺手抓命中行样本（LIMIT 封顶，token-cheap），把证据从「数字」变「行」。
    """
    cols = list(adapter.describe_table(table).keys())
    if not cols:
        return []
    rows = adapter.execute(f"SELECT * FROM {table} WHERE {where_sql} LIMIT {limit}", max_rows=limit)
    return [dict(zip(cols, r)) for r in rows]


def check_duplicate(adapter, table: str, key_cols: list[str]) -> list[Anomaly]:
    key = ", ".join(key_cols)
    n = adapter.execute(
        f"SELECT COUNT(*) FROM (SELECT {key} FROM {table} GROUP BY {key} HAVING COUNT(*) > 1)"
    )[0][0]
    if n > 0:
        inner = f"SELECT {key} FROM {table} GROUP BY {key} HAVING COUNT(*) > 1"
        lhs = key if len(key_cols) == 1 else f"({key})"
        where = f"{lhs} IN ({inner})"
        rows = sample_offending(adapter, table, where)
        return [Anomaly(type="duplicate", table=table, column=key,
                        evidence=Evidence(query=f"SELECT * FROM {table} WHERE {where} LIMIT 20",
                                          rows=rows, expected="无重复键", actual=f"{n} 组重复键"))]
    return []


def check_orphan(adapter, child: str, parent: str, child_fk: str, parent_pk: str) -> list[Anomaly]:
    # 口径：孤儿 = 非空外键但在父表找不到对应行；NULL 外键是「空值问题」（null_rate）不是「孤儿问题」，用 IS NOT NULL 排除。
    n = adapter.execute(
        f"SELECT COUNT(*) FROM {child} c LEFT JOIN {parent} p ON c.{child_fk} = p.{parent_pk} "
        f"WHERE p.{parent_pk} IS NULL AND c.{child_fk} IS NOT NULL"
    )[0][0]
    if n > 0:
        return [Anomaly(type="orphan", table=child, column=child_fk, evidence=f"{n} 行孤儿外键")]
    return []


def check_negative(adapter, table: str, column: str) -> list[Anomaly]:
    n = adapter.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} < 0")[0][0]
    if n > 0:
        return [Anomaly(type="value_range", table=table, column=column, evidence=f"{n} 行负值")]
    return []


def check_value_range(adapter, table: str, column: str, min_val=None, max_val=None) -> list[Anomaly]:
    """值域检查：column 不在 [min_val, max_val]（min/max 可 None 表示无界）。"""
    conds = []
    if min_val is not None:
        conds.append(f"{column} < {min_val}")
    if max_val is not None:
        conds.append(f"{column} > {max_val}")
    if not conds:
        return []
    n = adapter.execute(f"SELECT COUNT(*) FROM {table} WHERE {' OR '.join(conds)}")[0][0]
    if n > 0:
        return [Anomaly(type="value_range", table=table, column=column,
                        evidence=f"{n} 行超出值域 [{min_val}, {max_val}]")]
    return []


def check_time_inversion(adapter, column: str = "order_delivered_customer_date",
                         label: str = "交付日期早于下单日期") -> list[Anomaly]:
    """时间倒挂：某时间字段早于下单日期（< purchase），逻辑矛盾。"""
    n = adapter.execute(
        f"SELECT COUNT(*) FROM orders WHERE {column} IS NOT NULL "
        f"AND {column} < order_purchase_timestamp"
    )[0][0]
    if n > 0:
        return [Anomaly(type="time_inversion", table="orders",
                        column=column,
                        evidence=f"{n} 行{label}", metric_value=n)]
    return []


def check_future_date(adapter, max_date: str = "2018-12-31") -> list[Anomaly]:
    """未来日期：下单时间戳超出数据采集范围（Olist 止于 2018，超 max_date 判异常）。"""
    n = adapter.execute(
        f"SELECT COUNT(*) FROM orders WHERE order_purchase_timestamp > DATE '{max_date}'"
    )[0][0]
    if n > 0:
        return [Anomaly(type="future_date", table="orders",
                        column="order_purchase_timestamp",
                        evidence=f"{n} 行下单时间戳超出 {max_date}", metric_value=n)]
    return []


def check_null_rate(adapter, table: str, column: str, status_col: str | None = None,
                    status_value: str | None = None, threshold: float = 0.05) -> list[Anomaly]:
    """空值检查——可 status 分层（status_col 给定），也可全表（status_col=None）。"""
    cond = f"{status_col} = '{status_value}'" if status_col else "1=1"
    label = f"{status_value} 组" if status_col else "全表"
    total = adapter.execute(f"SELECT COUNT(*) FROM {table} WHERE {cond}")[0][0]
    null_cnt = adapter.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {cond} AND {column} IS NULL"
    )[0][0]
    if total > 0 and null_cnt / total > threshold:
        rate = null_cnt / total
        return [Anomaly(
            type="null_rate", table=table, column=column,
            evidence=f"{label} null 率 {rate:.0%} 超过阈值 {threshold:.0%}",
            metric_value=round(rate, 4), expected_range=f"<= {threshold:.0%}",
        )]
    return []


def run_rule_checks(adapter, null_rate_threshold: float = 0.05) -> list[Anomaly]:
    """跑全部 L0 规则，返回结构化异常清单。"""
    anomalies: list[Anomaly] = []
    anomalies += check_duplicate(adapter, "orders", ["order_id"])
    anomalies += check_duplicate(adapter, "order_items", ["order_id", "order_item_id"])
    anomalies += check_duplicate(adapter, "payments", ["order_id", "payment_sequential"])
    anomalies += check_duplicate(adapter, "reviews", ["review_id"])
    anomalies += check_orphan(adapter, "order_items", "orders", "order_id", "order_id")
    anomalies += check_negative(adapter, "order_items", "price")
    anomalies += check_negative(adapter, "order_items", "freight_value")
    anomalies += check_negative(adapter, "products", "product_weight_g")
    anomalies += check_value_range(adapter, "reviews", "review_score", 1, 5)
    anomalies += check_value_range(adapter, "payments", "payment_installments", 1, 24)
    # 空值按 status 分层：delivered 订单的交付日期不应为空
    anomalies += check_null_rate(adapter, "orders", "order_delivered_customer_date", "order_status", "delivered", null_rate_threshold)
    # 关键外键不应为空（全表检查，无 status 分层）
    anomalies += check_null_rate(adapter, "orders", "customer_id", threshold=0.0)
    # 时间逻辑：交付早于下单（倒挂）+ 预估送达早于下单（第二时间字段）+ 下单时间超出采集范围（未来日期）
    anomalies += check_time_inversion(adapter, "order_delivered_customer_date", "交付日期早于下单日期")
    anomalies += check_time_inversion(adapter, "order_estimated_delivery_date", "预估送达日期早于下单日期")
    anomalies += check_future_date(adapter)
    return anomalies


def check_amount_mismatch(adapter, tolerance: float = 0.01) -> list[Anomaly]:
    """跨表一致性：每单支付总额 vs 明细总额（price+freight），偏差超 tolerance 判异常。"""
    n = adapter.execute(f"""
        WITH pay AS (SELECT order_id, SUM(payment_value) AS paid FROM payments GROUP BY order_id),
             item AS (SELECT order_id, SUM(price + freight_value) AS amount FROM order_items GROUP BY order_id)
        SELECT COUNT(*) FROM pay JOIN item ON pay.order_id = item.order_id
        WHERE ABS(pay.paid - item.amount) > {tolerance}
    """)[0][0]
    if n > 0:
        return [Anomaly(type="amount_mismatch", table="orders",
                        column="payment_total vs item_total", severity="high",
                        evidence=f"{n} 单支付总额与明细总额不一致（偏差>{tolerance}）",
                        metric_value=n)]
    return []


def check_state_conflict(adapter) -> list[Anomaly]:
    """跨表一致性：已取消订单却存在评价（订单状态与评价表矛盾）。"""
    n = adapter.execute("""
        SELECT COUNT(*) FROM orders o JOIN reviews r ON o.order_id = r.order_id
        WHERE o.order_status = 'canceled'
    """)[0][0]
    if n > 0:
        return [Anomaly(type="state_conflict", table="orders", column="order_status",
                        severity="medium",
                        evidence=f"{n} 单已取消却有评价", metric_value=n)]
    return []


def check_zip_inconsistency(adapter) -> list[Anomaly]:
    """跨字段一致性：同一邮编映射到多个城市（地理维度表内部矛盾，Olist 真实存在）。"""
    n = adapter.execute("""
        SELECT COUNT(*) FROM (
            SELECT geolocation_zip_code_prefix FROM geolocation
            GROUP BY geolocation_zip_code_prefix HAVING COUNT(DISTINCT geolocation_city) > 1
        )
    """)[0][0]
    if n > 0:
        return [Anomaly(type="zip_inconsistency", table="geolocation",
                        column="geolocation_zip_code_prefix", severity="low",
                        evidence=f"{n} 个邮编映射到多个城市", metric_value=n)]
    return []


def run_consistency_checks(adapter) -> list[Anomaly]:
    """L0 跨表/跨字段一致性检查：按 FK/业务语义逐对校验，0 LLM、最可解释。"""
    anomalies: list[Anomaly] = []
    anomalies += check_amount_mismatch(adapter)
    anomalies += check_state_conflict(adapter)
    anomalies += check_zip_inconsistency(adapter)
    # 孤儿外键铺满星型模型 FK 网（§14 #5）
    anomalies += check_orphan(adapter, "order_items", "products", "product_id", "product_id")
    anomalies += check_orphan(adapter, "order_items", "sellers", "seller_id", "seller_id")
    anomalies += check_orphan(adapter, "payments", "orders", "order_id", "order_id")
    anomalies += check_orphan(adapter, "reviews", "orders", "order_id", "order_id")
    anomalies += check_orphan(adapter, "orders", "customers", "customer_id", "customer_id")
    return anomalies

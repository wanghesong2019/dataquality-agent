"""L0 规则断言检测：确定性、0 LLM、最可解释。"""
from dataquality_agent.models import Anomaly


def check_duplicate(conn, table: str, key_cols: list[str]) -> list[Anomaly]:
    key = ", ".join(key_cols)
    n = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT {key} FROM {table} GROUP BY {key} HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    if n > 0:
        return [Anomaly(type="duplicate", table=table, column=key, evidence=f"{n} 组重复键")]
    return []


def check_orphan(conn, child: str, parent: str, child_fk: str, parent_pk: str) -> list[Anomaly]:
    n = conn.execute(
        f"SELECT COUNT(*) FROM {child} c LEFT JOIN {parent} p ON c.{child_fk} = p.{parent_pk} "
        f"WHERE p.{parent_pk} IS NULL"
    ).fetchone()[0]
    if n > 0:
        return [Anomaly(type="orphan", table=child, column=child_fk, evidence=f"{n} 行孤儿外键")]
    return []


def check_negative(conn, table: str, column: str) -> list[Anomaly]:
    n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} < 0").fetchone()[0]
    if n > 0:
        return [Anomaly(type="value_range", table=table, column=column, evidence=f"{n} 行负值")]
    return []


def check_null_rate(conn, table: str, column: str, status_col: str,
                    status_value: str, threshold: float) -> list[Anomaly]:
    """空值检查——按 status 分层：只查某 status 组内的 null 率，避免业务正常 null 误报。"""
    total = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {status_col} = '{status_value}'"
    ).fetchone()[0]
    null_cnt = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {status_col} = '{status_value}' "
        f"AND {column} IS NULL"
    ).fetchone()[0]
    if total > 0 and null_cnt / total > threshold:
        rate = null_cnt / total
        return [Anomaly(
            type="null_rate", table=table, column=column,
            evidence=f"{status_value} 组 null 率 {rate:.0%} 超过阈值 {threshold:.0%}",
            metric_value=round(rate, 4), expected_range=f"<= {threshold:.0%}",
        )]
    return []


def run_rule_checks(conn) -> list[Anomaly]:
    """跑全部 L0 规则，返回结构化异常清单。"""
    anomalies: list[Anomaly] = []
    anomalies += check_duplicate(conn, "orders", ["order_id"])
    anomalies += check_duplicate(conn, "order_items", ["order_id", "order_item_id"])
    anomalies += check_orphan(conn, "order_items", "orders", "order_id", "order_id")
    anomalies += check_negative(conn, "order_items", "price")
    anomalies += check_negative(conn, "order_items", "freight_value")
    # 空值按 status 分层：delivered 订单的交付日期不应为空
    anomalies += check_null_rate(conn, "orders", "order_delivered_customer_date", "order_status", "delivered", 0.05)
    return anomalies


def check_amount_mismatch(conn, tolerance: float = 0.01) -> list[Anomaly]:
    """跨表一致性：每单支付总额 vs 明细总额（price+freight），偏差超 tolerance 判异常。"""
    n = conn.execute(f"""
        WITH pay AS (SELECT order_id, SUM(payment_value) AS paid FROM payments GROUP BY order_id),
             item AS (SELECT order_id, SUM(price + freight_value) AS amount FROM order_items GROUP BY order_id)
        SELECT COUNT(*) FROM pay JOIN item ON pay.order_id = item.order_id
        WHERE ABS(pay.paid - item.amount) > {tolerance}
    """).fetchone()[0]
    if n > 0:
        return [Anomaly(type="amount_mismatch", table="orders",
                        column="payment_total vs item_total", severity="high",
                        evidence=f"{n} 单支付总额与明细总额不一致（偏差>{tolerance}）",
                        metric_value=n)]
    return []


def check_state_conflict(conn) -> list[Anomaly]:
    """跨表一致性：已取消订单却存在评价（订单状态与评价表矛盾）。"""
    n = conn.execute("""
        SELECT COUNT(*) FROM orders o JOIN reviews r ON o.order_id = r.order_id
        WHERE o.order_status = 'canceled'
    """).fetchone()[0]
    if n > 0:
        return [Anomaly(type="state_conflict", table="orders", column="order_status",
                        severity="medium",
                        evidence=f"{n} 单已取消却有评价", metric_value=n)]
    return []


def check_zip_inconsistency(conn) -> list[Anomaly]:
    """跨字段一致性：同一邮编映射到多个城市（地理维度表内部矛盾，Olist 真实存在）。"""
    n = conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT geolocation_zip_code_prefix FROM geolocation
            GROUP BY geolocation_zip_code_prefix HAVING COUNT(DISTINCT geolocation_city) > 1
        )
    """).fetchone()[0]
    if n > 0:
        return [Anomaly(type="zip_inconsistency", table="geolocation",
                        column="geolocation_zip_code_prefix", severity="low",
                        evidence=f"{n} 个邮编映射到多个城市", metric_value=n)]
    return []


def run_consistency_checks(conn) -> list[Anomaly]:
    """L0 跨表/跨字段一致性检查：按 FK/业务语义逐对校验，0 LLM、最可解释。

    与 run_rule_checks（单表规则）的分工：单表规则查「一张表自己哪里不对」
    （重复/负值/空值），这里查「表与表之间的关系对不对」——金额对不上、状态矛盾、
    维度表内部矛盾、FK 悬空。这才是数据质量检测最招牌、最有区分度的一类。
    """
    anomalies: list[Anomaly] = []
    anomalies += check_amount_mismatch(conn)
    anomalies += check_state_conflict(conn)
    anomalies += check_zip_inconsistency(conn)
    # 孤儿外键铺满星型模型 FK 网（§14 #5）
    anomalies += check_orphan(conn, "order_items", "products", "product_id", "product_id")
    anomalies += check_orphan(conn, "order_items", "sellers", "seller_id", "seller_id")
    anomalies += check_orphan(conn, "payments", "orders", "order_id", "order_id")
    anomalies += check_orphan(conn, "reviews", "orders", "order_id", "order_id")
    anomalies += check_orphan(conn, "orders", "customers", "customer_id", "customer_id")
    return anomalies

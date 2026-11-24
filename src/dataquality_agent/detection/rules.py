"""L0 规则断言检测：确定性、0 LLM、最可解释。"""
from dataquality_agent.models import Anomaly, Evidence

from dataquality_agent.detection.catalog import default_assertions, run_catalog_checks


def sample_offending(adapter, table: str, where_sql: str, limit: int = 20) -> list[dict]:
    """采样命中行：SELECT * FROM {table} WHERE {where_sql} LIMIT {limit}，列名对齐返回 list[dict]。

    证据采集的核心：判定 fail 时顺手抓命中行样本（LIMIT 封顶，token-cheap），把证据从「数字」变「行」。
    """
    cols = list(adapter.describe_table(table).keys())
    if not cols:
        return []
    try:
        rows = adapter.execute(f"SELECT * FROM {table} WHERE {where_sql} LIMIT {limit}", max_rows=limit)
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        # 采样是增强步骤：报错不崩整次巡检（单检测器隔离），返回空列表，异常仍带 query + expected/actual
        return []


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
                                          rows=rows, expected="no duplicate keys", actual=f"{n} duplicate key groups"))]
    return []


def check_orphan(adapter, child: str, parent: str, child_fk: str, parent_pk: str) -> list[Anomaly]:
    # 口径：孤儿 = 非空外键但在父表找不到对应行；NULL 外键是「空值问题」（null_rate）不是「孤儿问题」，用 IS NOT NULL 排除。
    n = adapter.execute(
        f"SELECT COUNT(*) FROM {child} c LEFT JOIN {parent} p ON c.{child_fk} = p.{parent_pk} "
        f"WHERE p.{parent_pk} IS NULL AND c.{child_fk} IS NOT NULL"
    )[0][0]
    if n > 0:
        where = (f"{child_fk} IN (SELECT c.{child_fk} FROM {child} c LEFT JOIN {parent} p "
                 f"ON c.{child_fk} = p.{parent_pk} WHERE p.{parent_pk} IS NULL AND c.{child_fk} IS NOT NULL)")
        rows = sample_offending(adapter, child, where)
        return [Anomaly(type="orphan", table=child, column=child_fk,
                        evidence=Evidence(query=f"SELECT * FROM {child} WHERE {where} LIMIT 20",
                                          rows=rows, expected=f"no orphan FKs ({child}.{child_fk} ∈ {parent}.{parent_pk})",
                                          actual=f"{n} orphan rows"))]
    return []


def check_negative(adapter, table: str, column: str) -> list[Anomaly]:
    n = adapter.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} < 0")[0][0]
    if n > 0:
        where = f"{column} < 0"
        rows = sample_offending(adapter, table, where)
        return [Anomaly(type="value_range", table=table, column=column,
                        evidence=Evidence(query=f"SELECT * FROM {table} WHERE {where} LIMIT 20",
                                          rows=rows, expected=f"{column} >= 0", actual=f"{n} negative rows"))]
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
        where = " OR ".join(conds)
        rows = sample_offending(adapter, table, where)
        return [Anomaly(type="value_range", table=table, column=column,
                        evidence=Evidence(query=f"SELECT * FROM {table} WHERE {where} LIMIT 20",
                                          rows=rows, expected=f"value range [{min_val}, {max_val}]",
                                          actual=f"{n} rows out of range [{min_val}, {max_val}]"))]
    return []


def check_time_inversion(adapter, column: str = "order_delivered_customer_date",
                         label: str = "delivery date before purchase date") -> list[Anomaly]:
    """时间倒挂：某时间字段早于下单日期（< purchase），逻辑矛盾。"""
    n = adapter.execute(
        f"SELECT COUNT(*) FROM orders WHERE {column} IS NOT NULL "
        f"AND {column} < order_purchase_timestamp"
    )[0][0]
    if n > 0:
        where = f"{column} IS NOT NULL AND {column} < order_purchase_timestamp"
        rows = sample_offending(adapter, "orders", where)
        return [Anomaly(type="time_inversion", table="orders",
                        column=column,
                        evidence=Evidence(query=f"SELECT * FROM orders WHERE {where} LIMIT 20",
                                          rows=rows, expected=f"{label} does not hold ({column} >= purchase date)",
                                          actual=f"{n} rows {label}"), metric_value=n)]
    return []


def check_future_date(adapter, max_date: str = "2018-12-31") -> list[Anomaly]:
    """未来日期：下单时间戳超出数据采集范围（Olist 止于 2018，超 max_date 判异常）。"""
    n = adapter.execute(
        f"SELECT COUNT(*) FROM orders WHERE order_purchase_timestamp > DATE '{max_date}'"
    )[0][0]
    if n > 0:
        where = f"order_purchase_timestamp > DATE '{max_date}'"
        rows = sample_offending(adapter, "orders", where)
        return [Anomaly(type="future_date", table="orders",
                        column="order_purchase_timestamp",
                        evidence=Evidence(query=f"SELECT * FROM orders WHERE {where} LIMIT 20",
                                          rows=rows, expected=f"purchase time ≤ {max_date}",
                                          actual=f"{n} rows with purchase timestamp beyond {max_date}"), metric_value=n)]
    return []


def check_null_rate(adapter, table: str, column: str, status_col: str | None = None,
                    status_value: str | None = None, threshold: float = 0.05,
                    where: str | None = None) -> list[Anomaly]:
    """空值检查——可 status 分层（status_col 给定），也可全表（status_col=None），或原始 where 子句。"""
    if where is not None:
        cond = where
        label = "where group"
    elif status_col:
        cond = f"{status_col} = '{status_value}'"
        label = f"{status_value} group"
    else:
        cond = "1=1"
        label = "full table"
    total = adapter.execute(f"SELECT COUNT(*) FROM {table} WHERE {cond}")[0][0]
    null_cnt = adapter.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {cond} AND {column} IS NULL"
    )[0][0]
    if total > 0 and null_cnt / total > threshold:
        rate = null_cnt / total
        where = f"{cond} AND {column} IS NULL"
        rows = sample_offending(adapter, table, where)
        return [Anomaly(
            type="null_rate", table=table, column=column,
            evidence=Evidence(query=f"SELECT * FROM {table} WHERE {where} LIMIT 20",
                              rows=rows, expected=f"null rate ≤ {threshold:.0%}",
                              actual=f"{label} null rate {rate:.0%} exceeds threshold {threshold:.0%}"),
            metric_value=round(rate, 4), expected_range=f"<= {threshold:.0%}",
        )]
    return []


def run_rule_checks(adapter, null_rate_threshold: float = 0.05, assertions=None) -> list[Anomaly]:
    """跑全部 L0 规则：声明式断言目录（缺省内置 Olist 默认）+ 内置时间/未来日期检查。

    assertions 非空时整体替换默认目录（用户声明自己的断言）；否则用内置默认（回归不破）。
    """
    anomalies = run_catalog_checks(
        adapter,
        assertions if assertions is not None else default_assertions(null_rate_threshold),
    )
    # 时间逻辑：交付早于下单（倒挂）+ 预估送达早于下单（第二时间字段）+ 下单时间超出采集范围（未来日期）。
    # 同样隔离：非 Olist 数仓（无 orders 表）不能拖垮上面的目录结果。
    for check in (
        lambda: check_time_inversion(adapter, "order_delivered_customer_date", "delivery date before purchase date"),
        lambda: check_time_inversion(adapter, "order_estimated_delivery_date", "estimated delivery date before purchase date"),
        lambda: check_future_date(adapter),
    ):
        try:
            anomalies += check()
        except Exception:
            pass
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
        where = (
            f"order_id IN ("
            f"SELECT pay.order_id FROM "
            f"(SELECT order_id, SUM(payment_value) AS paid FROM payments GROUP BY order_id) pay "
            f"JOIN (SELECT order_id, SUM(price + freight_value) AS amount FROM order_items GROUP BY order_id) item "
            f"ON pay.order_id = item.order_id "
            f"WHERE ABS(pay.paid - item.amount) > {tolerance})"
        )
        rows = sample_offending(adapter, "orders", where)
        return [Anomaly(type="amount_mismatch", table="orders",
                        column="payment_total vs item_total", severity="high",
                        evidence=Evidence(query=f"SELECT * FROM orders WHERE {where} LIMIT 20",
                                          rows=rows, expected=f"deviation ≤ {tolerance}",
                                          actual=f"{n} orders payment total vs item total mismatch (deviation>{tolerance})"),
                        metric_value=n)]
    return []


def check_state_conflict(adapter) -> list[Anomaly]:
    """跨表一致性：已取消订单却存在评价（订单状态与评价表矛盾）。"""
    n = adapter.execute("""
        SELECT COUNT(*) FROM orders o JOIN reviews r ON o.order_id = r.order_id
        WHERE o.order_status = 'canceled'
    """)[0][0]
    if n > 0:
        where = ("order_id IN (SELECT o.order_id FROM orders o JOIN reviews r ON o.order_id = r.order_id "
                 "WHERE o.order_status = 'canceled')")
        rows = sample_offending(adapter, "orders", where)
        return [Anomaly(type="state_conflict", table="orders", column="order_status",
                        severity="medium",
                        evidence=Evidence(query=f"SELECT * FROM orders WHERE {where} LIMIT 20",
                                          rows=rows, expected="canceled orders have no reviews",
                                          actual=f"{n} canceled orders have reviews"), metric_value=n)]
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
        where = ("geolocation_zip_code_prefix IN (SELECT geolocation_zip_code_prefix FROM geolocation "
                 "GROUP BY geolocation_zip_code_prefix HAVING COUNT(DISTINCT geolocation_city) > 1)")
        rows = sample_offending(adapter, "geolocation", where)
        return [Anomaly(type="zip_inconsistency", table="geolocation",
                        column="geolocation_zip_code_prefix", severity="low",
                        evidence=Evidence(query=f"SELECT * FROM geolocation WHERE {where} LIMIT 20",
                                          rows=rows, expected="zip→city unique",
                                          actual=f"{n} zip codes map to multiple cities"), metric_value=n)]
    return []


def run_consistency_checks(adapter) -> list[Anomaly]:
    """L0 跨表/跨字段一致性检查（公式型，保持硬编码）：金额/状态/邮编。

    孤儿外键（referential）已迁移到声明式断言目录（catalog.default_assertions）。
    """
    anomalies: list[Anomaly] = []
    anomalies += check_amount_mismatch(adapter)
    anomalies += check_state_conflict(adapter)
    anomalies += check_zip_inconsistency(adapter)
    return anomalies

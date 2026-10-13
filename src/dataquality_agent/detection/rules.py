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

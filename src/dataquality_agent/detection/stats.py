"""L1 统计检测：学历史基线报偏差，0 LLM。"""
import math
import statistics
from datetime import date

from dataquality_agent.data.lineage import Lineage
from dataquality_agent.models import Anomaly


def zscore_detect(current: float, baseline: list[float], threshold: float = 3.0) -> bool:
    """
    点异常：current 是否偏离 baseline 均值超过 threshold 个标准差。
    隐含前提与局限：
    1. 隐含假设：基线数据近似服务正态分布。若基线严重偏态或重尾，3倍标准差阈值
    对应的实际置信度水平会显著偏离99.7%，需改用MAD等非参数方法
    2. 仅检测点异常：只判断单个current是否异常呢个，无法识别趋势突变、周期性破环等上下文异常
    3. 对离群值敏感：均值和标准差本身受基线中已有离群值污染，可能导致阈值被拉宽而漏检；    
    """
    if len(baseline) < 2:
        return False
    mean = statistics.mean(baseline)
    std = statistics.stdev(baseline)
    if std == 0:
        return False  # 基线恒定，无法判定偏移，不报（防误报）
    return abs(current - mean) / std > threshold


def psi(actual: dict, expected: dict, epsilon: float = 1e-3) -> float:
    """
    分布漂移：PSI 指数，越大漂移越严重。actual/expected 为 {类别: 计数}。
    1. 含义解释：这段脚本实现的是PSI(Population Stability Index，群体稳定性指数)，这是风控、信用
        评分及机器学习模型监控中衡量分布漂移的核心指标    
    """
    total_a = sum(actual.values())
    total_e = sum(expected.values())
    score = 0.0
    for c in set(actual) | set(expected):
        a = max(actual.get(c, 0) / total_a, epsilon)  # 下限防 log(0)
        e = max(expected.get(c, 0) / total_e, epsilon)
        score += (a - e) * math.log(a / e)
    return score


def _cat_dist(conn, table: str, cat_col: str, date_col: str, day=None) -> dict[str, int]:
    """某表某分类列在给定日期的计数分布。day 为 None 取全历史，否则只取那一天。"""
    if day is None:
        rows = conn.execute(
            f"SELECT {cat_col}, COUNT(*) FROM {table} GROUP BY {cat_col}"
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {cat_col}, COUNT(*) FROM {table} WHERE {date_col}::DATE = ?::DATE GROUP BY {cat_col}",
            [str(day)],
        ).fetchall()
    return {r[0]: r[1] for r in rows}


def detect_volume(conn, threshold: float = 3.0, lookback: int = 7,
                  metrics: tuple[str, ...] = ("orders",)) -> list[Anomaly]:
    """volume 点异常：最新一天各指标 vs 前 lookback 天基线（z-score）。多基线：orders + gmv。"""
    cols = ", ".join(metrics)
    rows = conn.execute(
        f"SELECT {cols} FROM daily_metrics ORDER BY order_date DESC LIMIT ?", [lookback + 1]
    ).fetchall()
    if len(rows) < 3:
        return []
    anomalies: list[Anomaly] = []
    for idx, metric in enumerate(metrics):
        current = rows[0][idx]
        baseline = [r[idx] for r in rows[1:]]
        if zscore_detect(current, baseline, threshold):
            anomalies.append(Anomaly(
                type="volume", table="daily_metrics", column=metric,
                evidence=f"最新日 {metric}={current} 偏离基线（|z| 超 {threshold}）",
                metric_value=current, expected_range=f"|z| <= {threshold}",
            ))
    return anomalies


def _dist_drift(conn, table: str, cat_col: str, date_col: str,
                threshold: float, min_count: int) -> list[Anomaly]:
    """某分类列「最新一天分布 vs 全历史基线」的 PSI 漂移检测（多基线共用的底层）。"""
    latest = conn.execute(f"SELECT MAX({date_col}::DATE) FROM {table}").fetchone()[0]
    if latest is None:
        return []
    cur = _cat_dist(conn, table, cat_col, date_col, latest)
    if sum(cur.values()) < min_count:
        return []  # 最新一天样本太少，无法判断分布漂移（防小样本误报）
    exp = _cat_dist(conn, table, cat_col, date_col, None)
    score = psi(cur, exp)
    if score > threshold:
        return [Anomaly(
            type="distribution", table=table, column=cat_col,
            evidence=f"{cat_col} 分布漂移 PSI={score:.3f} 超阈值 {threshold}",
            metric_value=round(score, 4), expected_range=f"PSI <= {threshold}",
        )]
    return []


def detect_distribution(conn, threshold: float = 0.10, min_count: int = 10,
                        dimensions: tuple[tuple[str, str, str], ...] = (
                            ("dwd_orders", "order_status", "order_purchase_timestamp"),
                        )) -> list[Anomaly]:
    """distribution 漂移：多基线（order_status + review_score）。每个维度 = (table, cat_col, date_col)。"""
    anomalies: list[Anomaly] = []
    for table, cat_col, date_col in dimensions:
        anomalies += _dist_drift(conn, table, cat_col, date_col, threshold, min_count)
    return anomalies


def check_freshness(dates: list[str], current_date: str, max_gap_days: int = 1) -> bool:
    """数据停更：最新分区日落后 current_date 超过容忍天数则报。dates 为已有日期字符串。"""
    if not dates:
        return True
    latest = max(dates)
    gap = (date.fromisoformat(current_date) - date.fromisoformat(latest)).days
    return gap > max_gap_days


def schema_diff(prev: dict, curr: dict) -> list[str]:
    """schema 漂移：返回列增/删/改类型的变更描述。prev 为快照，curr 为当前。"""
    changes: list[str] = []
    for col, typ in curr.items():
        if col not in prev:
            changes.append(f"added:{col}")
        elif prev[col] != typ:
            changes.append(f"type_changed:{col}:{prev[col]}->{typ}")
    for col in prev:
        if col not in curr:
            changes.append(f"removed:{col}")
    return changes


def detect_lineage_break(watermarks: dict[str, str], lineage: Lineage,
                         max_lag_days: int = 1) -> list[Anomaly]:
    """血缘断裂：下游表更新水位线落后其任一上游超过 max_lag_days 则报。"""
    anomalies: list[Anomaly] = []
    for table, wm in watermarks.items():
        for upstream in lineage.upstream(table):
            up_wm = watermarks.get(upstream)
            if up_wm is None:
                continue
            lag = (date.fromisoformat(up_wm) - date.fromisoformat(wm)).days
            if lag > max_lag_days:
                anomalies.append(Anomaly(
                    type="lineage_break", table=table, column=upstream,
                    evidence=f"{table} 水位线 {wm} 落后上游 {upstream} 的 {up_wm}（滞后 {lag} 天）",
                    metric_value=lag, expected_range=f"<= {max_lag_days} 天",
                ))
    return anomalies


def detect_freshness(watermarks: dict[str, str], current_date: str,
                     max_gap_days: int = 1) -> list[Anomaly]:
    """数据停更：各表水位线落后 current_date 超 max_gap_days 则报 freshness。"""
    anomalies: list[Anomaly] = []
    for table, wm in watermarks.items():
        if check_freshness([wm], current_date, max_gap_days):
            gap = (date.fromisoformat(current_date) - date.fromisoformat(wm)).days
            anomalies.append(Anomaly(
                type="freshness", table=table,
                evidence=f"{table} 水位线 {wm} 落后当前 {current_date}（滞后 {gap} 天）",
                metric_value=gap, expected_range=f"<= {max_gap_days} 天",
            ))
    return anomalies


def detect_schema_drift(curr_schema: dict, expected_schema: dict) -> list[Anomaly]:
    """schema 漂移：当前 schema 与期望快照逐表 diff，有变更则报。"""
    anomalies: list[Anomaly] = []
    for table, expected in expected_schema.items():
        changes = schema_diff(expected, curr_schema.get(table, {}))
        if changes:
            anomalies.append(Anomaly(
                type="schema_drift", table=table,
                evidence="; ".join(changes),
            ))
    return anomalies

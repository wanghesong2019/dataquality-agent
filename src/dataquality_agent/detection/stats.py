"""L1 统计检测：学历史基线报偏差，0 LLM。"""
import statistics
from datetime import date

from scipy.stats import chisquare

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


def chi2_drift(cur: dict, exp: dict, min_expected: float = 5.0) -> float:
    """分类列分布漂移：卡方拟合优度检验，返回 p 值（越小越像漂移）。

    cur = 最新窗口 {类别: 计数}（observed）；exp = 基线 {类别: 计数}（expected 来源）。
    期望计数 = 基线比例 × 最新窗口总量。expected < min_expected 的稀有类别合并进
    ``__other__``（Cochran 规则，保证卡方近似有效）；最新窗口出现基线没有的新类别直接判 p≈0。
    """
    obs_total = sum(cur.values())
    exp_total = sum(exp.values())
    if obs_total == 0 or exp_total == 0:
        return 1.0  # 无观测或无限基，无法判定，不报
    if any(o > 0 and exp.get(c, 0) == 0 for c, o in cur.items()):
        return 0.0
    ratio = obs_total / exp_total
    obs: dict[str, float] = {}
    expected: dict[str, float] = {}
    obs_other = 0.0
    exp_other = 0.0
    for c, e_base in exp.items():
        if e_base == 0:
            continue
        e = e_base * ratio
        if e < min_expected:
            obs_other += cur.get(c, 0)
            exp_other += e
        else:
            obs[c] = cur.get(c, 0)
            expected[c] = e
    if exp_other > 0:
        obs["__other__"] = obs_other
        expected["__other__"] = exp_other
    if len(expected) < 2:
        return 1.0  # 合并后自由度不足，无法检验，不报
    f_obs = [obs[c] for c in expected]
    f_exp = [expected[c] for c in expected]
    _, p = chisquare(f_obs, f_exp)
    return float(p)


def _cat_dist(adapter, table: str, cat_col: str, date_col: str, day=None) -> dict[str, int]:
    """某表某分类列在给定日期的计数分布。day 为 None 取全历史，否则只取那一天。"""
    if day is None:
        rows = adapter.execute(
            f"SELECT {cat_col}, COUNT(*) FROM {table} GROUP BY {cat_col}"
        )
    else:
        rows = adapter.execute(
            f"SELECT {cat_col}, COUNT(*) FROM {table} WHERE {date_col}::DATE = '{day}'::DATE GROUP BY {cat_col}"
        )
    return {r[0]: r[1] for r in rows}


def detect_volume(adapter, threshold: float = 3.0, lookback: int = 7,
                  metrics: tuple[str, ...] = ("orders",), min_count: int = 100) -> list[Anomaly]:
    """volume 点异常：最新一天各指标 vs 前 lookback 天基线（z-score）。多基线：orders + gmv。"""
    cols = ", ".join(metrics)
    rows = adapter.execute(
        f"SELECT {cols} FROM daily_metrics ORDER BY order_date DESC LIMIT {lookback + 1}"
    )
    if len(rows) < 3:
        return []
    anomalies: list[Anomaly] = []
    for idx, metric in enumerate(metrics):
        current = rows[0][idx]
        if current < min_count:
            continue
        baseline = [r[idx] for r in rows[1:]]
        if zscore_detect(current, baseline, threshold):
            anomalies.append(Anomaly(
                type="volume", table="daily_metrics", column=metric,
                evidence=f"最新日 {metric}={current} 偏离基线（|z| 超 {threshold}）",
                metric_value=current, expected_range=f"|z| <= {threshold}",
            ))
    return anomalies


def _dist_drift(adapter, table: str, cat_col: str, date_col: str,
                alpha: float, min_count: int) -> list[Anomaly]:
    """某分类列「最新一天分布 vs 全历史基线」的卡方漂移检测（多基线共用的底层）。"""
    latest = adapter.execute(f"SELECT MAX({date_col}::DATE) FROM {table}")[0][0]
    if latest is None:
        return []
    cur = _cat_dist(adapter, table, cat_col, date_col, latest)
    if sum(cur.values()) < min_count:
        return []
    exp = _cat_dist(adapter, table, cat_col, date_col, None)
    p = chi2_drift(cur, exp)
    if p < alpha:
        return [Anomaly(
            type="distribution", table=table, column=cat_col,
            evidence=f"{cat_col} 分布漂移 χ² p={p:.3g} < {alpha}",
            metric_value=round(p, 6), expected_range=f"χ² p >= {alpha}",
        )]
    return []


def detect_distribution(adapter, alpha: float = 0.05, min_count: int = 100,
                        dimensions: tuple[tuple[str, str, str], ...] = (
                            ("dwd_orders", "order_status", "order_purchase_timestamp"),
                        )) -> list[Anomaly]:
    """distribution 漂移：多基线（order_status + review_score）。每个维度 = (table, cat_col, date_col)。"""
    anomalies: list[Anomaly] = []
    for table, cat_col, date_col in dimensions:
        anomalies += _dist_drift(adapter, table, cat_col, date_col, alpha, min_count)
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
    """血缘断裂：下游表水位线落后其构建上游超过 max_lag_days 则报。"""
    anomalies: list[Anomaly] = []
    for table, wm in watermarks.items():
        for upstream in lineage.build_upstream(table):
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

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

"""L1 统计检测：学历史基线报偏差，0 LLM。"""
import math
import statistics
from datetime import date


def zscore_detect(current: float, baseline: list[float], threshold: float = 3.0) -> bool:
    """点异常：current 是否偏离 baseline 均值超过 threshold 个标准差。"""
    if len(baseline) < 2:
        return False
    mean = statistics.mean(baseline)
    std = statistics.stdev(baseline)
    if std == 0:
        return False  # 基线恒定，无法判定偏移，不报（防误报）
    return abs(current - mean) / std > threshold


def psi(actual: dict, expected: dict, epsilon: float = 1e-3) -> float:
    """分布漂移：PSI 指数，越大漂移越严重。actual/expected 为 {类别: 计数}。"""
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

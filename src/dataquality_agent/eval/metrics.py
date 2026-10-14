"""评估指标：把检测/归因/整改结果与 ground-truth 对比，算出可量化效果。"""
from dataclasses import dataclass


@dataclass
class DetectionMetrics:
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float


def evaluate_detection(detected, injected) -> DetectionMetrics:
    """对比检测结果与注入的 ground-truth，按 (type, table) 匹配算 precision/recall/F1。"""
    det = {(a.type, a.table) for a in detected}
    inj = {(i.type, i.table) for i in injected}
    tp = len(det & inj)
    fp = len(det - inj)
    fn = len(inj - det)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return DetectionMetrics(tp=tp, fp=fp, fn=fn, precision=precision, recall=recall, f1=f1)


def accuracy(predicted: list[str], actual: list[str]) -> float:
    """分类正确率（用于归因正确率：predicted 根因 vs actual 根因，需等长一一对应）。"""
    if not actual:
        return 0.0
    return sum(p == a for p, a in zip(predicted, actual)) / len(actual)


def success_rate(total: int, succeeded: int) -> float:
    """成功率（整改/端到端：succeeded / total）。total=0 时返回 0。"""
    return succeeded / total if total else 0.0

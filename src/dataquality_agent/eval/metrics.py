"""评估指标：把检测/归因/整改结果与 ground-truth 对比，算出可量化效果。"""
from dataclasses import dataclass, field


@dataclass
class DetectionMetrics:
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float


@dataclass
class EvalReport:
    """一次完整评估的量化结果（面试报数用）。"""

    detection: DetectionMetrics
    detection_by_type: dict[str, DetectionMetrics] = field(default_factory=dict)
    attribution_accuracy: float = 0.0
    remediation_success: float = 0.0
    end_to_end_success: float = 0.0
    latency_seconds: float = 0.0
    total_tokens: int = 0
    total_cost: float = 0.0
    llm_calls: int = 0


def _keys(items) -> set:
    """把 Anomaly / InjectedAnomaly 列表规约成 (type, table) 集合，供对齐计算。"""
    return {(a.type, a.table) for a in items}


def evaluate_detection(detected, injected) -> DetectionMetrics:
    """对比检测结果与注入的 ground-truth，按 (type, table) 匹配算 precision/recall/F1。"""
    det = _keys(detected)
    inj = _keys(injected)
    tp = len(det & inj)
    fp = len(det - inj)
    fn = len(inj - det)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return DetectionMetrics(tp=tp, fp=fp, fn=fn, precision=precision, recall=recall, f1=f1)


def evaluate_detection_by_type(detected, injected) -> dict[str, DetectionMetrics]:
    """按异常类型分别算 P/R/F1（面试能报"duplicate 的 F1 是多少"）。"""
    det = _keys(detected)
    inj = _keys(injected)
    types = sorted({k[0] for k in det} | {k[0] for k in inj})
    result = {}
    for t in types:
        det_t = {k for k in det if k[0] == t}
        inj_t = {k for k in inj if k[0] == t}
        tp = len(det_t & inj_t)
        fp = len(det_t - inj_t)
        fn = len(inj_t - det_t)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        result[t] = DetectionMetrics(tp=tp, fp=fp, fn=fn, precision=precision, recall=recall, f1=f1)
    return result


def accuracy(predicted: list[str], actual: list[str]) -> float:
    """分类正确率（需等长一一对应）。"""
    if not actual:
        return 0.0
    return sum(p == a for p, a in zip(predicted, actual)) / len(actual)


def success_rate(total: int, succeeded: int) -> float:
    """成功率：succeeded / total。total=0 时返回 0。"""
    return succeeded / total if total else 0.0


def attribution_accuracy(detected, diagnoses, injected) -> float:
    """归因正确率：检测到的异常映射到 ground-truth，比较 Diagnosis.root_cause_category 是否一致。
    前提：detected 与 diagnoses 按索引一一对应（diagnose 节点按 anomalies 顺序生成）。
    误报（无 ground-truth）的异常不计入。"""
    gt = {(i.type, i.table): i.root_cause_category for i in injected}
    matched = total = 0
    for a, d in zip(detected, diagnoses):
        cat = gt.get((a.type, a.table))
        if cat is None:
            continue
        total += 1
        if d.root_cause_category == cat:
            matched += 1
    return matched / total if total else 0.0


def remediation_success(detected_before, detected_after, injected) -> float:
    """整改成功率（复检口径）：修复后重跑检测，注入且被检出的异常消失才算整改成功。"""
    before = _keys(detected_before)
    after = _keys(detected_after)
    inj = _keys(injected)
    to_fix = inj & before  # 需要整改 = 注入过且修复前被检出
    if not to_fix:
        return 0.0
    fixed = to_fix - after  # 修复后不再被检出 = 整改成功
    return len(fixed) / len(to_fix)


def end_to_end_success(detected, diagnoses, detected_after, injected) -> float:
    """端到端闭环成功率：注入 → 检出 → 归因对 → 整改后消失，全链走通才算成功。
    分母 = 全部注入异常（任一环节漏掉都算该异常端到端失败）。"""
    gt = {(i.type, i.table): i.root_cause_category for i in injected}
    after = _keys(detected_after)
    success = 0
    for a, d in zip(detected, diagnoses):
        key = (a.type, a.table)
        if key not in gt:
            continue  # 误报不计入端到端成功
        if d.root_cause_category == gt[key] and key not in after:
            success += 1
    return success / len(injected) if injected else 0.0


def total_latency(stats: dict[str, float]) -> float:
    """各阶段耗时汇总（秒）。"""
    return sum(stats.values())

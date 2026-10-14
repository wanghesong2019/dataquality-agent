import pytest

from dataquality_agent.data.injector import InjectedAnomaly
from dataquality_agent.eval.metrics import (
    accuracy,
    attribution_accuracy,
    end_to_end_success,
    evaluate_detection,
    evaluate_detection_by_type,
    remediation_success,
    success_rate,
    total_latency,
)
from dataquality_agent.models import Anomaly, Diagnosis


def _inj(type, table, cat):
    return InjectedAnomaly(type=type, table=table, root_cause="x", root_cause_category=cat, location=table)


def test_evaluate_detection_perfect():
    detected = [Anomaly(type="duplicate", table="orders"), Anomaly(type="orphan", table="order_items")]
    injected = [
        InjectedAnomaly(type="duplicate", table="orders", root_cause="dup", root_cause_category="脏数据注入", location="orders"),
        InjectedAnomaly(type="orphan", table="order_items", root_cause="del", root_cause_category="上游任务失败", location="order_items"),
    ]
    r = evaluate_detection(detected, injected)
    assert (r.tp, r.fp, r.fn) == (2, 0, 0)
    assert r.precision == 1.0 and r.recall == 1.0 and r.f1 == 1.0


def test_evaluate_detection_fp_and_fn():
    detected = [Anomaly(type="duplicate", table="orders")]  # 漏检 orphan
    injected = [
        InjectedAnomaly(type="duplicate", table="orders", root_cause="dup", root_cause_category="脏数据注入", location="orders"),
        InjectedAnomaly(type="orphan", table="order_items", root_cause="del", root_cause_category="上游任务失败", location="order_items"),
    ]
    r = evaluate_detection(detected, injected)
    assert (r.tp, r.fp, r.fn) == (1, 0, 1)
    assert r.precision == 1.0 and r.recall == 0.5


def test_evaluate_detection_false_positive():
    detected = [Anomaly(type="value_range", table="orders")]  # 误报：没注入这个
    injected = [InjectedAnomaly(type="duplicate", table="orders", root_cause="dup", root_cause_category="脏数据注入", location="orders")]
    r = evaluate_detection(detected, injected)
    assert (r.tp, r.fp, r.fn) == (0, 1, 1)
    assert r.precision == 0.0


def test_accuracy():
    assert accuracy(["a", "b", "a"], ["a", "b", "c"]) == 2 / 3


def test_success_rate():
    assert success_rate(10, 8) == 0.8
    assert success_rate(0, 0) == 0.0


def test_evaluate_detection_by_type():
    detected = [
        Anomaly(type="duplicate", table="orders"),
        Anomaly(type="orphan", table="order_items"),
        Anomaly(type="value_range", table="order_items"),  # 误报
    ]
    injected = [_inj("duplicate", "orders", "脏数据注入"), _inj("orphan", "order_items", "上游任务失败")]
    by_type = evaluate_detection_by_type(detected, injected)
    assert by_type["duplicate"].precision == 1.0
    assert by_type["orphan"].recall == 1.0
    assert by_type["value_range"].precision == 0.0  # 误报类型 P=0


def test_attribution_accuracy():
    detected = [Anomaly(type="duplicate", table="orders"), Anomaly(type="orphan", table="order_items")]
    diagnoses = [
        Diagnosis(root_cause_category="脏数据注入", confidence=0.9),  # 对
        Diagnosis(root_cause_category="脏数据注入", confidence=0.5),  # 错（应是上游任务失败）
    ]
    injected = [_inj("duplicate", "orders", "脏数据注入"), _inj("orphan", "order_items", "上游任务失败")]
    assert attribution_accuracy(detected, diagnoses, injected) == 0.5


def test_remediation_success_recheck():
    injected = [_inj("duplicate", "orders", "脏数据注入"), _inj("orphan", "order_items", "上游任务失败")]
    detected_before = [Anomaly(type="duplicate", table="orders"), Anomaly(type="orphan", table="order_items")]
    detected_after = [Anomaly(type="orphan", table="order_items")]  # duplicate 修好了
    assert remediation_success(detected_before, detected_after, injected) == 0.5


def test_end_to_end_success():
    injected = [_inj("duplicate", "orders", "脏数据注入"), _inj("orphan", "order_items", "上游任务失败")]
    detected = [Anomaly(type="duplicate", table="orders"), Anomaly(type="orphan", table="order_items")]
    diagnoses = [
        Diagnosis(root_cause_category="脏数据注入", confidence=0.9),
        Diagnosis(root_cause_category="上游任务失败", confidence=0.8),
    ]
    detected_after = []  # 全修好了
    assert end_to_end_success(detected, diagnoses, detected_after, injected) == 1.0


def test_total_latency():
    assert total_latency({"l0_rules": 0.1, "l1_lineage": 0.2}) == pytest.approx(0.3)

from dataquality_agent.data.injector import InjectedAnomaly
from dataquality_agent.eval.metrics import classify_failures, end_to_end_success
from dataquality_agent.models import Anomaly, Diagnosis


def _inj(type, table, cat):
    return InjectedAnomaly(type=type, table=table, root_cause="x", root_cause_category=cat, location=table)


def _ano(type, table):
    return Anomaly(type=type, table=table)


def test_classify_all_success():
    injected = [_inj("duplicate", "orders", "脏数据注入"), _inj("null_rate", "orders", "脏数据注入")]
    detected = [_ano("duplicate", "orders"), _ano("null_rate", "orders")]
    diagnoses = [Diagnosis(root_cause_category="脏数据注入", confidence=0.9),
                 Diagnosis(root_cause_category="脏数据注入", confidence=0.9)]
    ft = classify_failures(detected, diagnoses, [], injected)
    assert (ft.success, ft.detection_failure, ft.attribution_failure, ft.remediation_failure) == (2, 0, 0, 0)
    assert ft.success_rate == 1.0


def test_classify_detection_failure():
    injected = [_inj("duplicate", "orders", "脏数据注入")]
    ft = classify_failures([], [], [], injected)  # 漏检
    assert ft.detection_failure == 1
    assert ft.success_rate == 0.0


def test_classify_attribution_failure():
    injected = [_inj("orphan", "order_items", "上游任务失败")]
    detected = [_ano("orphan", "order_items")]
    diagnoses = [Diagnosis(root_cause_category="脏数据注入", confidence=0.5)]  # 归因错
    ft = classify_failures(detected, diagnoses, [], injected)
    assert ft.attribution_failure == 1


def test_classify_remediation_failure():
    injected = [_inj("duplicate", "orders", "脏数据注入")]
    detected = [_ano("duplicate", "orders")]
    diagnoses = [Diagnosis(root_cause_category="脏数据注入", confidence=0.9)]
    after = [_ano("duplicate", "orders")]  # 整改后仍检出
    ft = classify_failures(detected, diagnoses, after, injected)
    assert ft.remediation_failure == 1


def test_end_to_end_success_consistent_with_taxonomy():
    injected = [_inj("duplicate", "orders", "脏数据注入"), _inj("orphan", "order_items", "上游任务失败")]
    detected = [_ano("duplicate", "orders"), _ano("orphan", "order_items")]
    diagnoses = [Diagnosis(root_cause_category="脏数据注入", confidence=0.9),
                 Diagnosis(root_cause_category="上游任务失败", confidence=0.8)]
    # duplicate 修好、orphan 没修好
    after = [_ano("orphan", "order_items")]
    ft = classify_failures(detected, diagnoses, after, injected)
    assert end_to_end_success(detected, diagnoses, after, injected) == ft.success_rate == 0.5
    assert (ft.success, ft.remediation_failure) == (1, 1)

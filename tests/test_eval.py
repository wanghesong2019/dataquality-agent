from dataquality_agent.data.injector import InjectedAnomaly
from dataquality_agent.eval.metrics import accuracy, evaluate_detection, success_rate
from dataquality_agent.models import Anomaly


def test_evaluate_detection_perfect():
    detected = [Anomaly(type="duplicate", table="orders"), Anomaly(type="orphan", table="order_items")]
    injected = [
        InjectedAnomaly(type="duplicate", table="orders", root_cause="dup"),
        InjectedAnomaly(type="orphan", table="order_items", root_cause="del"),
    ]
    r = evaluate_detection(detected, injected)
    assert (r.tp, r.fp, r.fn) == (2, 0, 0)
    assert r.precision == 1.0 and r.recall == 1.0 and r.f1 == 1.0


def test_evaluate_detection_fp_and_fn():
    detected = [Anomaly(type="duplicate", table="orders")]  # 漏检 orphan
    injected = [
        InjectedAnomaly(type="duplicate", table="orders", root_cause="dup"),
        InjectedAnomaly(type="orphan", table="order_items", root_cause="del"),
    ]
    r = evaluate_detection(detected, injected)
    assert (r.tp, r.fp, r.fn) == (1, 0, 1)
    assert r.precision == 1.0 and r.recall == 0.5


def test_evaluate_detection_false_positive():
    detected = [Anomaly(type="value_range", table="orders")]  # 误报：没注入这个
    injected = [InjectedAnomaly(type="duplicate", table="orders", root_cause="dup")]
    r = evaluate_detection(detected, injected)
    assert (r.tp, r.fp, r.fn) == (0, 1, 1)
    assert r.precision == 0.0


def test_accuracy():
    assert accuracy(["a", "b", "a"], ["a", "b", "c"]) == 2 / 3


def test_success_rate():
    assert success_rate(10, 8) == 0.8
    assert success_rate(0, 0) == 0.0

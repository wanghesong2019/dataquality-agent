"""确定性评估 F1 门禁：自包含样本数据上跑，检测 F1 必须 == 1.0（CI 硬门禁）。"""
from dataquality_agent.eval.deterministic import run_deterministic_eval


def test_deterministic_f1_is_perfect(mini_warehouse):
    report = run_deterministic_eval(mini_warehouse)
    assert report.detection.precision == 1.0
    assert report.detection.recall == 1.0
    assert report.detection.f1 == 1.0

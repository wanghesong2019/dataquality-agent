"""确定性评估 F1 门禁：自包含样本数据上跑，检测 F1 必须 == 1.0（CI 硬门禁）。"""
from dataquality_agent.eval.deterministic import run_deterministic_eval


def test_deterministic_f1_is_perfect(mini_warehouse):
    report = run_deterministic_eval(mini_warehouse)
    assert report.detection.precision == 1.0
    assert report.detection.recall == 1.0
    assert report.detection.f1 == 1.0


def test_eval_asserts_evidence_completeness(mini_warehouse):
    """证据完整性门禁：每条 fail 异常都带非空 query，且 rows 封顶 20。"""
    report = run_deterministic_eval(mini_warehouse)
    assert report.detection.f1 == 1.0
    assert report.anomalies, "确定性 eval 应暴露检测到的异常"
    for a in report.anomalies:
        # L0 行型规则有 query+rows；L1 统计无命中行，靠 expected/actual（对齐计划 Task 3「query 或 expected/actual 非空」）
        assert a.evidence.query.strip() or (a.evidence.expected and a.evidence.actual), f"{a.type} 无证据"
        assert a.evidence.rows is None or len(a.evidence.rows) <= 20

from dataquality_agent.eval.trajectory import evaluate_trajectories, evaluate_trajectory
from dataquality_agent.models import Diagnosis


def _chain(*calls):
    """把 (name, args) 序列拼成 evidence_chain 的字符串形式。"""
    return [f"{name}{args} -> ok" for name, args in calls]


def test_trajectory_clean_passes():
    v = evaluate_trajectory(_chain(
        ("schema", "({'table':'orders'})"),
        ("lineage", "({'table':'orders'})"),
        ("cases", "({'query':'duplicate'})"),
    ))
    assert v.passed
    assert v.redundant_calls == 0
    assert v.evidence_sufficient
    assert v.schema_before_sql is None  # 没用 sql


def test_trajectory_redundant_fails():
    v = evaluate_trajectory(_chain(
        ("schema", "({'table':'orders'})"),
        ("schema", "({'table':'orders'})"),
    ))
    assert not v.passed
    assert v.redundant_calls == 1


def test_trajectory_sql_without_schema_fails():
    v = evaluate_trajectory(_chain(("sql", "('SELECT * FROM orders')")))
    assert v.schema_before_sql is False
    assert not v.passed


def test_trajectory_schema_before_sql_passes():
    v = evaluate_trajectory(_chain(
        ("schema", "({'table':'orders'})"),
        ("sql", "('SELECT * FROM orders')"),
    ))
    assert v.schema_before_sql is True
    assert v.passed


def test_trajectory_report_aggregation():
    d1 = Diagnosis(root_cause_category="脏数据注入", confidence=0.9,
                   evidence_chain=_chain(("schema", "(orders)"), ("lineage", "(orders)")))
    d2 = Diagnosis(root_cause_category="脏数据注入", confidence=0.9,
                   evidence_chain=_chain(("schema", "(orders)"), ("schema", "(orders)")))
    report = evaluate_trajectories([d1, d2])
    assert report.evaluated == 2
    assert report.pass_rate == 0.5
    assert report.total_redundant == 1


def test_trajectory_report_empty():
    report = evaluate_trajectories([])
    assert report.evaluated == 0
    assert report.pass_rate == 0.0

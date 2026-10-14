from dataquality_agent.eval.judge import Rubric, build_judge_prompt, judge, judge_agreement
from dataquality_agent.models import Anomaly, Diagnosis

RUBRIC = Rubric(dimensions=["根因正确性", "证据充分性", "可操作性"], description="评估归因质量")


def test_judge_parses_scores():
    def fake_model(prompt):
        return '{"根因正确性": 5, "证据充分性": 3, "可操作性": 4, "rationale": "ok"}'

    anomaly = Anomaly(type="duplicate", table="orders")
    output = Diagnosis(root_cause_category="脏数据注入", confidence=0.9)
    s = judge(fake_model, anomaly, output, RUBRIC)
    assert s.scores == {"根因正确性": 5, "证据充分性": 3, "可操作性": 4}
    assert s.rationale == "ok"


def test_judge_bad_json_defaults_to_1():
    def fake_model(prompt):
        return "not json"

    anomaly = Anomaly(type="duplicate", table="orders")
    output = Diagnosis(root_cause_category="脏数据注入", confidence=0.9)
    s = judge(fake_model, anomaly, output, RUBRIC)
    assert s.scores == {"根因正确性": 1, "证据充分性": 1, "可操作性": 1}  # 解析失败降级 1 分


def test_judge_agreement():
    judge_scores = [{"a": 5, "b": 3}, {"a": 4, "b": 4}]
    human = [{"a": 5, "b": 4}, {"a": 4, "b": 4}]
    # 维度 a 全对(2)，维度 b 对 1 错 1 → 4 维度里 3 对 = 0.75
    assert judge_agreement(judge_scores, human) == 0.75


def test_build_judge_prompt_contains_dimensions():
    p = build_judge_prompt(
        Anomaly(type="duplicate", table="orders"),
        Diagnosis(root_cause_category="脏数据注入", confidence=0.9),
        RUBRIC,
    )
    assert "根因正确性" in p and "证据充分性" in p and "可操作性" in p

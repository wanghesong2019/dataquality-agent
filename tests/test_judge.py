import json

from dataquality_agent.eval.judge import Rubric, build_judge_prompt, judge, judge_agreement
from dataquality_agent.models import Anomaly, Diagnosis

RUBRIC = Rubric(dimensions=["根因正确性", "证据充分性", "可操作性"], description="评估归因质量")


def _fake_model(arguments: str):
    """返回一个带 .chat 的假模型：只调用 submit_judge_score，arguments 可注入（含坏 JSON）。"""

    class FakeModel:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "", "tool_calls": [
                {"id": "1", "function": {"name": "submit_judge_score", "arguments": arguments}}
            ]}

    return FakeModel()


def test_judge_parses_scores():
    s = judge(_fake_model(json.dumps({"根因正确性": 5, "证据充分性": 3, "可操作性": 4, "rationale": "ok"})),
              Anomaly(type="duplicate", table="orders"),
              Diagnosis(root_cause_category="脏数据注入", confidence=0.9),
              RUBRIC)
    assert s.scores == {"根因正确性": 5, "证据充分性": 3, "可操作性": 4}
    assert s.rationale == "ok"


def test_judge_bad_json_defaults_to_1():
    s = judge(_fake_model("not json"),
              Anomaly(type="duplicate", table="orders"),
              Diagnosis(root_cause_category="脏数据注入", confidence=0.9),
              RUBRIC)
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

"""LLM-as-a-Judge：用 rubric 给归因/整改质量打分，人工抽检校准。

知识地图（为什么需要它）
--------------------------
`metrics.py` 只能回答"对不对"（二元：归因类别对不对、整改有没有让异常消失），但归因/
整改还有"质量"维度是二元表达不了的——归因对了但证据链是空的、整改 SQL 能跑但不是
最优，这些需要更细的评分。

做法：再拿一个 LLM 按 rubric（评分维度）打 1~5 分，把"质量"变成数字。但 LLM 打分
本身有 bias/随机性，所以配 `judge_agreement` 做"人工抽检校准"：人工标 10%，比对 LLM
分 vs 人工分的一致率，达标才敢信这个"法官"。

结构化输出 + 降级：用 function calling（`submit_judge_score` 工具 + tool_choice）把打分
约束成 schema 硬校验——维度名由 rubric 动态生成、类型强制整数 1~5，从源头消除"格式失败
被伪装成低分"。`judge` 解析仍失败时每个维度降级 1 分（最差），不抛异常——和模型输出护栏
同一套原则。
"""
import json

from pydantic import BaseModel


class Rubric(BaseModel):
    """评分维度清单：每个维度一条说明。"""

    dimensions: list[str]
    description: str


class JudgeScore(BaseModel):
    """LLM 法官对单项产出的评分。"""

    scores: dict[str, int]  # 维度名 -> 1~5 分
    rationale: str = ""


def build_judge_prompt(anomaly, output, rubric: Rubric, context=None) -> str:
    """把「异常 + 产出 + rubric」拼成打分 prompt。context 可选：如整改对应的根因 Diagnosis。"""
    dims = ", ".join(rubric.dimensions)
    lines = [
        "You are a data quality evaluator. Score the following output against the rubric (each dimension 1~5, 5=best).",
        f"rubric: {rubric.description}",
        f"dimensions: {dims}",
        f"anomaly: {anomaly.model_dump()}",
    ]
    if context is not None:
        lines.append(f"context (attributed root cause): {context.model_dump()}")
    lines.append(f"output: {output.model_dump()}")
    lines.append('Output JSON with fields: {"<dimension>": <integer 1~5>, "rationale": "one-sentence reason"}')
    return "\n".join(lines)


def _judge_schema(rubric: Rubric) -> dict:
    """把 rubric 维度动态转成 function calling 的 JSON Schema（维度名 → 1~5 整数）。

    坑：维度名不能含空格——DeepSeek 的 function calling 会把含空格的 property name 截断
    （如 "action_type 归类" 被生成成 "action_type，缺失闭合引号），导致 arguments JSON
    解析失败、全维度兜底 1 分。所以 rubric.dimensions 必须用紧凑无空格的键名。
    """
    return {
        "type": "function",
        "function": {
            "name": "submit_judge_score",
            "description": "Score one output against the rubric",
            "parameters": {
                "type": "object",
                "properties": {
                    **{d: {"type": "integer", "minimum": 1, "maximum": 5} for d in rubric.dimensions},
                    "rationale": {"type": "string"},
                },
                "required": rubric.dimensions,
            },
        },
    }


def judge(model, anomaly, output, rubric: Rubric, context=None) -> JudgeScore:
    """调 LLM 按 rubric 打分。model 需有 .chat(messages, tools, tool_choice)。context 可选：如整改对应的根因 Diagnosis。"""
    resp = model.chat(
        [{"role": "user", "content": build_judge_prompt(anomaly, output, rubric, context)}],
        tools=[_judge_schema(rubric)],
        tool_choice={"type": "function", "function": {"name": "submit_judge_score"}},
    )
    args = {}
    for call in resp.get("tool_calls", []):
        if call.get("function", {}).get("name") == "submit_judge_score":
            try:
                args = json.loads(call["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}
            break
    scores = {d: int(args.get(d, 1)) for d in rubric.dimensions}
    return JudgeScore(scores=scores, rationale=str(args.get("rationale", "")))


def judge_agreement(judge_scores: list[dict[str, int]], human_labels: list[dict[str, int]], tolerance: int = 0) -> float:
    """人工抽检校准：逐维度比对法官分 vs 人工分，返回一致率。

    tolerance 允许 ±N 算一致——Likert 量表的相邻档（4 vs 5）方向一致但精确值差一档，
    exact 匹配会把它判为不一致；±1 容差更能反映"rough agreement"。默认 0 = exact。
    """
    if not human_labels:
        return 0.0
    total = matched = 0
    for js, hl in zip(judge_scores, human_labels):
        for dim, label in hl.items():  # 以人工标注的维度为准
            total += 1
            if abs(js.get(dim, 0) - label) <= tolerance:
                matched += 1
    return matched / total if total else 0.0

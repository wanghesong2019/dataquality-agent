"""LLM-as-a-Judge：用 rubric 给归因/整改质量打分，人工抽检校准。

知识地图（为什么需要它）
--------------------------
`metrics.py` 只能回答"对不对"（二元：归因类别对不对、整改有没有让异常消失），但归因/
整改还有"质量"维度是二元表达不了的——归因对了但证据链是空的、整改 SQL 能跑但不是
最优，这些需要更细的评分。

做法：再拿一个 LLM 按 rubric（评分维度）打 1~5 分，把"质量"变成数字。但 LLM 打分
本身有 bias/随机性，所以配 `judge_agreement` 做"人工抽检校准"：人工标 10%，比对 LLM
分 vs 人工分的一致率，达标才敢信这个"法官"。

结构化输出 + 降级：`build_judge_prompt` 强制输出 JSON `{维度: 分, rationale}`；`judge`
解析失败时每个维度降级 1 分（最差），不抛异常——和模型输出护栏同一套原则。
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


def build_judge_prompt(anomaly, output, rubric: Rubric) -> str:
    """把「异常 + 产出 + rubric」拼成打分 prompt（要求输出结构化 JSON）。"""
    dims = "、".join(rubric.dimensions)
    return (
        "你是数据质量评估员。请按 rubric 给以下产出打分（每个维度 1~5 分，5=最好）。\n"
        f"rubric：{rubric.description}\n"
        f"评分维度：{dims}\n"
        f"异常：{anomaly.model_dump()}\n"
        f"产出：{output.model_dump()}\n"
        '输出 JSON，字段必须为：{"<维度名>": <1~5 的整数>, "rationale": "一句话理由"}'
    )


def judge(model, anomaly, output, rubric: Rubric) -> JudgeScore:
    """调 LLM 按 rubric 打分，返回结构化 JudgeScore。model 是可调用对象（返回字符串）。"""
    resp = model(build_judge_prompt(anomaly, output, rubric))
    try:
        data = json.loads(resp)
    except json.JSONDecodeError:
        data = {}
    scores = {d: int(data.get(d, 1)) for d in rubric.dimensions}
    return JudgeScore(scores=scores, rationale=str(data.get("rationale", "")))


def judge_agreement(judge_scores: list[dict[str, int]], human_labels: list[dict[str, int]]) -> float:
    """人工抽检校准：逐维度比对法官分 vs 人工分，返回一致率（证明 LLM-as-a-Judge 靠谱）。"""
    if not human_labels:
        return 0.0
    total = matched = 0
    for js, hl in zip(judge_scores, human_labels):
        for dim, label in hl.items():  # 以人工标注的维度为准
            total += 1
            if js.get(dim) == label:
                matched += 1
    return matched / total if total else 0.0

"""LLM 重排：检索粗筛后，用 LLM 按相关性精排候选（Cross-Encoder 精排的 LLM 版）。"""
import json


def llm_rerank(query: str, candidates: list[dict], model, top_k: int = 3) -> list[dict]:
    """用 LLM 按与 query 的相关性重排候选案例，返回 top_k。

    model 是返回字符串的可调用对象（如 LLMAdapter）。None 或候选 <=1 时直接返回原序。
    LLM 漏排的候选按原顺序补在末尾（防漏召回），坏 JSON 则整体降级原序。
    """
    if model is None or len(candidates) <= 1:
        return candidates[:top_k]

    prompt = (
        "请按与查询的相关性从高到低重排下面的案例，只返回案例 id 的 JSON 数组（如 [\"a\", \"b\"]）。\n"
        f"查询：{query}\n候选：\n"
        + "\n".join(f"- id={c['id']}: {c['text']}" for c in candidates)
    )
    resp = (model(prompt) or "").strip()
    ids: list[str] = []
    start, end = resp.find("["), resp.rfind("]")
    if start >= 0 and end >= start:
        try:
            ids = json.loads(resp[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            ids = []

    by_id = {c["id"]: c for c in candidates}
    ranked = [by_id[i] for i in ids if i in by_id]
    seen = {c["id"] for c in ranked}
    ranked += [c for c in candidates if c["id"] not in seen]  # 漏排补回
    return ranked[:top_k]

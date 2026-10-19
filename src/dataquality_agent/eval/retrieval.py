"""检索评测：Recall@K / MRR（证明检索链路靠谱，不只是"感觉能找到"）。"""


def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Recall@K：检索结果前 k 个里命中了多少相关文档（召回覆盖）。"""
    if not relevant_ids:
        return 0.0
    return len(set(retrieved_ids[:k]) & relevant_ids) / len(relevant_ids)


def mrr(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    """MRR：第一个相关文档排名的倒数（越靠前越接近 1，没命中 = 0）。"""
    for i, doc_id in enumerate(retrieved_ids, 1):
        if doc_id in relevant_ids:
            return 1.0 / i
    return 0.0

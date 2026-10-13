"""混合检索（dense 向量 + BM25 稀疏）→ RRF 融合。"""
import math

from dataquality_agent.rag.embedder import Embedder


class Retriever:
    """案例检索器：dense（语义相似）+ sparse（关键词）两路召回，RRF 融合排序。"""

    def __init__(self, embedder: Embedder, rrf_k: int = 60):
        self.embedder = embedder
        self.rrf_k = rrf_k
        self.docs: list[dict] = []

    def index(self, cases: list[dict]) -> None:
        """cases: [{id, text}]。"""
        texts = [c["text"] for c in cases]
        vecs = self.embedder.embed(texts)
        for c, v in zip(cases, vecs):
            self.docs.append({
                "id": c["id"], "text": c["text"],
                "dense": v, "tokens": c["text"].split(),
            })

    def search(self, query: str, k: int = 3) -> list[dict]:
        q_dense = self.embedder.embed([query])[0]
        q_tokens = query.split()
        dense = [(d["id"], self._cosine(q_dense, d["dense"])) for d in self.docs]
        sparse = [(d["id"], self._bm25(q_tokens, d["tokens"])) for d in self.docs]
        ranked_ids = self._rrf(dense, sparse, k)
        by_id = {d["id"]: d for d in self.docs}
        return [by_id[i] for i in ranked_ids]

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(x * x for x in b)) or 1.0
        return dot / (na * nb)

    @staticmethod
    def _bm25(q_tokens: list[str], doc_tokens: list[str]) -> float:
        # 简化 BM25：词频加权 + 文档长度归一化（demo 足够，抓表名/字段名关键词）
        if not doc_tokens:
            return 0.0
        score = 0.0
        for q in q_tokens:
            tf = doc_tokens.count(q)
            if tf:
                score += tf / len(doc_tokens)
        return score

    def _rrf(self, dense, sparse, k: int) -> list[str]:
        # Reciprocal Rank Fusion：score = Σ 1/(k + rank)
        dense_sorted = [i for i, _ in sorted(dense, key=lambda x: -x[1])]
        sparse_sorted = [i for i, _ in sorted(sparse, key=lambda x: -x[1])]
        dr = {i: r + 1 for r, i in enumerate(dense_sorted)}
        sr = {i: r + 1 for r, i in enumerate(sparse_sorted)}
        fused = {}
        for i in set(dr) | set(sr):
            fused[i] = 1.0 / (self.rrf_k + dr.get(i, 10 ** 6)) + 1.0 / (self.rrf_k + sr.get(i, 10 ** 6))
        return sorted(fused, key=fused.get, reverse=True)[:k]

"""混合检索（dense 向量 + BM25 稀疏）→ RRF 融合。"""
import math

from dataquality_agent.rag.embedder import Embedder


class Retriever:
    """案例检索器：dense（语义相似）+ sparse（标准 BM25）两路召回，RRF 融合排序。"""

    def __init__(self, embedder: Embedder, rrf_k: int = 60, bm25_k1: float = 1.5, bm25_b: float = 0.75):
        self.embedder = embedder
        self.rrf_k = rrf_k
        self.bm25_k1 = bm25_k1
        self.bm25_b = bm25_b
        self.docs: list[dict] = []
        self._df: dict[str, int] = {}  # term -> 包含该 term 的文档数（IDF 用）
        self._avgdl: float = 0.0       # 平均文档长度（BM25 长度归一化用）

    def index(self, cases: list[dict]) -> None:
        """cases: [{id, text}]。建索引时顺带算 document frequency 和平均文档长度（BM25 需要）。"""
        texts = [c["text"] for c in cases]
        vecs = self.embedder.embed(texts)
        tokenized = [c["text"].split() for c in cases]
        self._df = {}
        for toks in tokenized:
            for t in set(toks):
                self._df[t] = self._df.get(t, 0) + 1
        self._avgdl = (sum(len(t) for t in tokenized) / len(tokenized)) if tokenized else 0.0
        for c, v, toks in zip(cases, vecs, tokenized):
            self.docs.append({"id": c["id"], "text": c["text"], "dense": v, "tokens": toks})

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

    def _bm25(self, q_tokens: list[str], doc_tokens: list[str]) -> float:
        """标准 BM25：IDF × 词频饱和 + 文档长度归一化（k1/b 参数）。"""
        if not doc_tokens or not self.docs:
            return 0.0
        n_docs = len(self.docs)
        dl = len(doc_tokens)
        avgdl = max(self._avgdl, 1.0)
        score = 0.0
        for q in q_tokens:
            df = self._df.get(q, 0)
            if df == 0:
                continue
            idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)
            tf = doc_tokens.count(q)
            denom = tf + self.bm25_k1 * (1 - self.bm25_b + self.bm25_b * dl / avgdl)
            score += idf * (tf * (self.bm25_k1 + 1.0)) / denom
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

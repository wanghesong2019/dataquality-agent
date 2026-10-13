"""Embedding 接口 + 可插拔实现。"""
from abc import ABC, abstractmethod


class Embedder(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """把文本列表转成向量列表。"""


class BagOfWordsEmbedder(Embedder):
    """词袋向量——确定性的 demo/测试用 embedder。生产可换成 BGE-M3 等中文模型（同接口）。"""

    def __init__(self, vocab: list[str]):
        self.vocab = vocab
        self._idx = {w: i for i, w in enumerate(vocab)}

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = []
        for t in texts:
            v = [0.0] * len(self.vocab)
            for w in t.split():
                if w in self._idx:
                    v[self._idx[w]] = 1.0
            vecs.append(v)
        return vecs

"""Embedding 接口 + 可插拔实现。"""
import os
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


class OpenAIEmbedder(Embedder):
    """OpenAI 兼容 `/embeddings` 接口的 embedding 客户端（接自部署的 BGE-M3 等模型）。

    服务可用 TEI / vLLM / Ollama 等以 OpenAI 兼容协议暴露 BGE-M3；
    base_url 传服务根路径（含 `/v1`），model 传服务端注册的模型名。
    """

    def __init__(self, base_url: str | None = None, model: str | None = None,
                 api_key: str | None = None):
        self.base_url = (base_url or os.environ.get("EMBEDDING_BASE_URL", "")).rstrip("/")
        self.model = model or os.environ.get("EMBEDDING_MODEL", "")
        self.api_key = api_key or os.environ.get("EMBEDDING_API_KEY", "")

    def embed(self, texts: list[str]) -> list[list[float]]:
        import requests  # 延迟导入，避免测试环境硬依赖

        if not self.base_url or not self.model:
            raise RuntimeError("OpenAIEmbedder 需要 base_url 和 model（或 env EMBEDDING_BASE_URL / EMBEDDING_MODEL）")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = requests.post(
            f"{self.base_url}/embeddings",
            headers=headers,
            json={"model": self.model, "input": texts},
            timeout=60,
        )
        resp.raise_for_status()
        # 服务端返回不一定按输入顺序，按 index 排序保证一一对应
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

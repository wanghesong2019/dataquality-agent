from dataquality_agent.rag.embedder import BagOfWordsEmbedder, OpenAIEmbedder
from dataquality_agent.rag.retriever import Retriever

CASES = [
    {"id": "c1", "text": "订单 主键 重复"},
    {"id": "c2", "text": "支付 方式 分布 漂移"},
    {"id": "c3", "text": "交付 日期 空值 异常"},
]


def make_retriever():
    vocab = sorted({w for c in CASES for w in c["text"].split()})
    r = Retriever(BagOfWordsEmbedder(vocab))
    r.index(CASES)
    return r


def test_retrieve_matching_case():
    top = make_retriever().search("订单 主键 重复", k=1)
    assert top[0]["id"] == "c1"


def test_retrieve_distribution_case():
    top = make_retriever().search("支付 方式 漂移", k=1)
    assert top[0]["id"] == "c2"


def test_retrieve_null_case():
    top = make_retriever().search("交付 空值", k=1)
    assert top[0]["id"] == "c3"


def test_openai_embedder_calls_embeddings_endpoint(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [
                {"index": 1, "embedding": [0.1, 0.2]},
                {"index": 0, "embedding": [0.3, 0.4]},
            ]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr("requests.post", fake_post)
    emb = OpenAIEmbedder(base_url="http://localhost:8000/v1", model="BAAI/bge-m3", api_key="sk-x")
    vecs = emb.embed(["你好", "世界"])
    assert captured["url"] == "http://localhost:8000/v1/embeddings"
    assert captured["json"] == {"model": "BAAI/bge-m3", "input": ["你好", "世界"]}
    assert captured["headers"]["Authorization"] == "Bearer sk-x"
    # 按 index 排序，保证返回顺序和输入一致
    assert vecs == [[0.3, 0.4], [0.1, 0.2]]

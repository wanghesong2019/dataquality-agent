from dataquality_agent.rag.embedder import BagOfWordsEmbedder
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

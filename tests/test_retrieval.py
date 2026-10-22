from dataquality_agent.eval.retrieval import evaluate_retrieval, mrr, recall_at_k
from dataquality_agent.rag.tokenizer import tokenize


def test_recall_at_k():
    assert recall_at_k(["a", "b", "c"], {"a", "c"}, k=3) == 1.0  # 全命中
    assert recall_at_k(["a", "b", "c"], {"a", "c"}, k=1) == 0.5  # 前 1 个只命中 a


def test_recall_at_k_empty_relevant():
    assert recall_at_k(["a"], set(), k=1) == 0.0


def test_mrr():
    assert mrr(["a", "b", "c"], {"a"}) == 1.0   # 第 1 位命中
    assert mrr(["b", "a", "c"], {"a"}) == 0.5   # 第 2 位命中
    assert mrr(["b", "c"], {"a"}) == 0.0        # 没命中


def test_tokenize_splits_chinese():
    """字符 bigram 分词把中文词切开（text.split() 做不到），同时保留英文 token。"""
    toks = tokenize("orders 主键重复")
    assert "主键" in toks
    assert "重复" in toks
    assert "orders" in toks
    assert "，" not in toks  # 纯标点被过滤


def test_evaluate_retrieval_aggregates():
    """evaluate_retrieval 把 recall_at_k/mrr 接到真实 retriever 上，正确聚合平均。"""
    class FakeRetriever:
        def search(self, query, k=3):
            return [{"id": "a"}, {"id": "b"}]

    report = evaluate_retrieval(FakeRetriever(), [{"query": "q", "relevant": "a"}], k=3)
    assert report["recall_at_k"] == 1.0
    assert report["mrr"] == 1.0

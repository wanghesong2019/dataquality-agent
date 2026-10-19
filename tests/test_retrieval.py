from dataquality_agent.eval.retrieval import mrr, recall_at_k


def test_recall_at_k():
    assert recall_at_k(["a", "b", "c"], {"a", "c"}, k=3) == 1.0  # 全命中
    assert recall_at_k(["a", "b", "c"], {"a", "c"}, k=1) == 0.5  # 前 1 个只命中 a


def test_recall_at_k_empty_relevant():
    assert recall_at_k(["a"], set(), k=1) == 0.0


def test_mrr():
    assert mrr(["a", "b", "c"], {"a"}) == 1.0   # 第 1 位命中
    assert mrr(["b", "a", "c"], {"a"}) == 0.5   # 第 2 位命中
    assert mrr(["b", "c"], {"a"}) == 0.0        # 没命中

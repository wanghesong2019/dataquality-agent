"""Retriever.search 门禁：返回可读案例（id+text），不泄漏内部 dense 向量/tokens。

dense 向量是 scoring 内部状态，若随 search 结果泄漏，assemble_evidence 会 str() 出
~70k 字符的浮点向量塞进每个 prompt，撑爆 token（实测 thin 诊断 ~3.3 万 token/call）。
"""
from dataquality_agent.rag.embedder import BagOfWordsEmbedder
from dataquality_agent.rag.retriever import Retriever


def test_search_returns_readable_cases_only():
    ret = Retriever(BagOfWordsEmbedder(["orders", "主键", "重复"]))
    ret.index([
        {"id": "duplicate_orders", "text": "orders 主键重复"},
        {"id": "orphan_order_items", "text": "order_items 孤儿外键"},
    ])
    results = ret.search("orders 主键重复", k=2)
    assert results, "应命中案例"
    for r in results:
        assert set(r.keys()) == {"id", "text"}, f"泄漏内部字段：{set(r.keys())}"

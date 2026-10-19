from dataquality_agent.rag.rerank import llm_rerank

CANDIDATES = [
    {"id": "c1", "text": "a"},
    {"id": "c2", "text": "b"},
    {"id": "c3", "text": "c"},
]


def test_rerank_orders_by_llm():
    def fake_model(prompt):
        return '["c2", "c1", "c3"]'

    ranked = llm_rerank("query", CANDIDATES, fake_model, top_k=3)
    assert [c["id"] for c in ranked] == ["c2", "c1", "c3"]


def test_rerank_no_model_keeps_order():
    ranked = llm_rerank("query", CANDIDATES, None, top_k=3)
    assert [c["id"] for c in ranked] == ["c1", "c2", "c3"]


def test_rerank_bad_json_falls_back_to_original_order():
    def fake_model(prompt):
        return "not json"

    ranked = llm_rerank("query", CANDIDATES, fake_model, top_k=3)
    assert [c["id"] for c in ranked] == ["c1", "c2", "c3"]  # 坏 JSON 降级原序


def test_rerank_missing_ids_appended_at_end():
    def fake_model(prompt):
        return '["c3"]'  # 漏排 c1、c2

    ranked = llm_rerank("query", CANDIDATES, fake_model, top_k=3)
    assert [c["id"] for c in ranked] == ["c3", "c1", "c2"]  # 漏排补回原序

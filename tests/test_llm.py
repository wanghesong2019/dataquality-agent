import pytest

from dataquality_agent.llm import LLMAdapter


def test_llm_adapter_retries_on_failure():
    calls = {"n": 0}

    class FakeClient:
        def chat(self, prompt):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("temporary")
            return "ok"

    adapter = LLMAdapter(FakeClient())
    assert adapter("hello") == "ok"
    assert calls["n"] == 2  # 失败一次后重试成功


def test_llm_adapter_gives_up_after_max_retries():
    class AlwaysFail:
        def chat(self, prompt):
            raise ValueError("always")

    adapter = LLMAdapter(AlwaysFail())
    with pytest.raises(ValueError):
        adapter("hello", max_retries=2)


def test_llm_adapter_tracks_cost():
    class FakeClient:
        def chat(self, prompt):
            return "ok"

    adapter = LLMAdapter(FakeClient())
    adapter("hello world")
    assert adapter.cost_ledger.llm_calls == 1
    assert adapter.cost_ledger.total_tokens > 0


def test_llm_adapter_emits_trace():
    from dataquality_agent.observability.tracing import Tracer

    class FakeClient:
        def chat(self, prompt):
            return "ok"

    tracer = Tracer()
    adapter = LLMAdapter(FakeClient(), tracer=tracer)
    adapter("hi")
    assert len(tracer.spans) == 1
    assert tracer.spans[0].tokens == len("hi") + len("ok")

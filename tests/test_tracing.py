import pytest

from dataquality_agent.observability.tracing import LangfuseBackend, Span, Tracer


def test_tracer_records_span():
    t = Tracer()
    s = t.start_span("llm", input="hello")
    t.end_span(s, output="world", tokens=10, cost=0.01)
    assert len(t.spans) == 1
    assert t.spans[0].name == "llm"
    assert t.spans[0].tokens == 10
    assert t.spans[0].cost == 0.01
    assert t.spans[0].duration >= 0


def test_tracer_aggregates_tokens_and_cost():
    t = Tracer()
    for _ in range(2):
        s = t.start_span("llm")
        t.end_span(s, tokens=5, cost=0.02)
    assert t.total_tokens() == 10
    assert t.total_cost() == pytest.approx(0.04)


def test_langfuse_backend_noop_when_unconfigured():
    b = LangfuseBackend()  # 无 key → no-op
    s = Span(name="x", start=0.0, tokens=1)
    b.record(s)  # 不应抛异常

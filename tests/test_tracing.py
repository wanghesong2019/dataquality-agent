import pytest

from dataquality_agent.observability.tracing import LangfuseBackend, Span, Tracer, trace_step


class _RecordingBackend:
    """Fake backend：捕获 record() 收到的 span，验证 Tracer → backend 接线（不用真连 Langfuse）。"""

    def __init__(self):
        self.recorded = []

    def record(self, span: Span) -> None:
        self.recorded.append(span)


# ---------- Span ----------

def test_span_duration():
    s = Span(name="x", start=1.0, end=3.5)
    assert s.duration == pytest.approx(2.5)


def test_span_default_fields():
    s = Span(name="x", start=0.0)
    assert s.input == "" and s.output == "" and s.tokens == 0 and s.cost == 0.0
    assert s.parent is None and s.children == []


# ---------- Tracer 基础 ----------

def test_tracer_records_span():
    t = Tracer()
    s = t.start_span("llm", input="hello")
    t.end_span(s, output="world", tokens=10, cost=0.01)
    assert len(t.spans) == 1
    assert t.spans[0].name == "llm"
    assert t.spans[0].input == "hello"
    assert t.spans[0].output == "world"
    assert t.spans[0].tokens == 10
    assert t.spans[0].cost == pytest.approx(0.01)
    assert t.spans[0].duration >= 0


def test_tracer_aggregates_tokens_and_cost():
    t = Tracer()
    for _ in range(2):
        s = t.start_span("llm")
        t.end_span(s, tokens=5, cost=0.02)
    assert t.total_tokens() == 10
    assert t.total_cost() == pytest.approx(0.04)


def test_tracer_total_duration():
    t = Tracer()
    t.spans.append(Span(name="a", start=0.0, end=2.0))
    t.spans.append(Span(name="b", start=1.0, end=3.0))
    assert t.total_duration() == pytest.approx(4.0)  # (2-0) + (3-1)


def test_tracer_empty_aggregates():
    t = Tracer()
    assert t.total_tokens() == 0
    assert t.total_cost() == 0.0
    assert t.total_duration() == 0.0
    assert t.root_duration() == 0.0
    assert t.roots == []


# ---------- 树结构（Span.parent + ContextVar 自动父挂） ----------

def test_start_span_explicit_parent():
    t = Tracer()
    parent = t.start_span("node")
    child = t.start_span("llm", parent=parent)
    assert child.parent is parent
    assert parent.children == [child]


def test_span_context_manager_autoparents():
    """with t.span() 期间，内层 span 自动挂到外层（ContextVar 自动父挂）。"""
    t = Tracer()
    with t.span("node:diagnose"):
        with t.span("llm"):
            pass
        with t.span("tool:schema"):
            pass
    roots = t.roots
    assert len(roots) == 1
    assert [c.name for c in roots[0].children] == ["llm", "tool:schema"]


def test_roots_are_only_top_level():
    t = Tracer()
    with t.span("node"):
        with t.span("llm"):
            pass
    with t.span("another-node"):
        pass
    assert [r.name for r in t.roots] == ["node", "another-node"]


def test_context_var_nesting_three_levels():
    t = Tracer()
    with t.span("node"):
        with t.span("tool:cases"):
            with t.span("retrieve"):
                pass
    node = t.roots[0]
    tool = node.children[0]
    assert tool.children[0].name == "retrieve"


def test_context_var_reset_after_span():
    """span() 上下文退出后，当前 span 恢复为外层（不会串到下一个 span）。"""
    t = Tracer()
    with t.span("outer"):
        pass
    # 退出 outer 后，再开的 span 应该是新的根，而不是挂到 outer 下
    with t.span("sibling"):
        pass
    assert [r.name for r in t.roots] == ["outer", "sibling"]


# ---------- render_tree / summary_by_name / root_duration ----------

def test_render_tree_indents_by_depth():
    t = Tracer()
    with t.span("node"):
        with t.span("llm"):
            pass
    lines = t.render_tree().splitlines()
    assert lines[0].startswith("node")
    assert lines[1].startswith("  llm")  # 子节点缩进 2 格


def test_summary_by_name_aggregates():
    t = Tracer()
    for _ in range(2):
        with t.span("llm"):
            pass
    with t.span("tool"):
        pass
    agg = t.summary_by_name()
    assert agg["llm"]["count"] == 2
    assert agg["tool"]["count"] == 1
    assert set(agg["llm"]) == {"count", "duration", "tokens"}


def test_root_duration_excludes_children():
    """root_duration 只算根 span（避免父子重叠重复计），total_duration 算全部。"""
    t = Tracer()
    with t.span("node"):
        with t.span("llm"):
            pass
    assert t.root_duration() == pytest.approx(sum(s.duration for s in t.roots))
    assert t.total_duration() >= t.root_duration()


# ---------- trace_step 装饰器 ----------

def test_trace_step_passthrough_without_tracer():
    @trace_step(None, "node:x")
    def f(x):
        return x + 1
    assert f(1) == 2


def test_trace_step_creates_span_and_returns_result():
    t = Tracer()

    @trace_step(t, "node:diagnose")
    def f():
        return "ok"
    assert f() == "ok"
    assert [s.name for s in t.spans] == ["node:diagnose"]


def test_trace_step_nests_under_current_span():
    """trace_step 装饰的函数在已有 span 内执行时，自动挂成子节点。"""
    t = Tracer()
    with t.span("outer"):
        @trace_step(t, "inner")
        def f():
            return 1
        f()
    assert t.roots[0].children[0].name == "inner"


# ---------- backend 接线 ----------

def test_backend_receives_spans_on_end_span():
    b = _RecordingBackend()
    t = Tracer(backend=b)
    s = t.start_span("llm")
    t.end_span(s, output="o", tokens=3)
    assert len(b.recorded) == 1
    assert b.recorded[0].name == "llm"
    assert b.recorded[0].output == "o"
    assert b.recorded[0].tokens == 3


def test_backend_receives_spans_on_context_manager():
    b = _RecordingBackend()
    t = Tracer(backend=b)
    with t.span("node"):
        pass
    assert len(b.recorded) == 1
    assert b.recorded[0].name == "node"


def test_langfuse_backend_noop_when_unconfigured():
    b = LangfuseBackend()  # 无 key → no-op
    s = Span(name="x", start=0.0, tokens=1)
    b.record(s)  # 不应抛异常

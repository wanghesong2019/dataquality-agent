from dataquality_agent.observability.tracing import Tracer, trace_step


def test_nested_spans_form_tree():
    t = Tracer()
    with t.span("node:diagnose"):
        with t.span("llm"):
            pass
        with t.span("tool:schema"):
            with t.span("retrieve"):
                pass
    assert len(t.spans) == 4
    roots = t.roots
    assert len(roots) == 1
    assert roots[0].name == "node:diagnose"
    assert [c.name for c in roots[0].children] == ["llm", "tool:schema"]
    assert roots[0].children[1].children[0].name == "retrieve"


def test_root_duration_no_double_count():
    t = Tracer()
    with t.span("node"):
        with t.span("llm"):
            pass
    # total 含嵌套（node+llm 重叠），root 只算 node
    assert t.root_duration() == sum(s.duration for s in t.roots)
    assert t.total_duration() >= t.root_duration()


def test_summary_by_name():
    t = Tracer()
    for _ in range(2):
        with t.span("llm"):
            pass
    with t.span("tool"):
        pass
    agg = t.summary_by_name()
    assert agg["llm"]["count"] == 2
    assert agg["tool"]["count"] == 1


def test_render_tree_indents():
    t = Tracer()
    with t.span("node"):
        with t.span("llm"):
            pass
    text = t.render_tree()
    lines = text.splitlines()
    assert lines[0].startswith("node")
    assert lines[1].startswith("  llm")  # 缩进 2 格


def test_trace_step_passthrough_no_tracer():
    @trace_step(None, "node:x")
    def f(x):
        return x + 1
    assert f(1) == 2


def test_trace_step_creates_span():
    t = Tracer()

    @trace_step(t, "node:diagnose")
    def f():
        return "ok"
    assert f() == "ok"
    assert [s.name for s in t.spans] == ["node:diagnose"]

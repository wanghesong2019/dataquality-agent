"""可观测：Trace（步骤级 span 树）+ 成本台账。默认记录到内存（测试/本地），配 Langfuse 后上报。

知识地图（为什么需要它）
--------------------------
回答"每次巡检跑了多少 Token、花了多少钱、哪一步最慢"。分两块：
- Trace：一次运行里发生了什么——节点（inspect/diagnose/remediate/approve/report）、每次
  LLM 调用、每次工具调用、每次检索，都是一个 `Span`，按 `parent` 指针组成 Trace 树。
- 成本台账（`CostLedger`）：累计 token/成本/调用次数。

步骤级 Trace 的关键设计：`Span.parent` + ContextVar 自动父挂。节点用 `tracer.span()` 上下文
管理器把自己设为「当前 span」，期间发生的 LLM/工具/检索 span 自动挂成它的子节点，调用方
不用显式传 parent（这正是 OTel 的做法）。可观测是"旁路"——`LangfuseBackend` 惰性导入 +
未配置 no-op；集成点 `LLMAdapter.chat` 每次调用埋一个 span，token 计数和 CostLedger 共用
同一份，两者永远对得上。
"""
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


# 当前正在执行的 span（用于自动父挂：with tracer.span(...) 期间，子 span 自动挂到它下面）
_current_span: ContextVar["Span | None"] = ContextVar("dqa_current_span", default=None)


@dataclass
class Span:
    """一次 LLM 调用 / 工具调用 / 节点执行的一个观测记录（按 parent 组成 Trace 树）。"""

    name: str
    start: float
    input: str = ""
    output: str = ""
    tokens: int = 0
    cost: float = 0.0
    end: float = 0.0
    parent: "Span | None" = None
    children: list["Span"] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


class Tracer:
    """记录 pipeline 运行 + 各步骤 span（节点/LLM/工具/检索），组成 Trace 树。backend 可插拔。"""

    def __init__(self, backend=None):
        self.backend = backend
        self.spans: list[Span] = []

    def start_span(self, name: str, input: str = "", parent: Span | None = None) -> Span:
        """开一个 span；parent 缺省时自动挂到「当前 span」（ContextVar），组成树。"""
        if parent is None:
            parent = _current_span.get()
        span = Span(name=name, start=time.time(), input=input, parent=parent)
        if parent is not None:
            parent.children.append(span)
        self.spans.append(span)
        return span

    def _finish(self, span: Span) -> None:
        span.end = time.time()
        if self.backend is not None:
            self.backend.record(span)

    def end_span(self, span: Span, output: str = "", tokens: int = 0, cost: float = 0.0) -> None:
        span.output = output
        span.tokens = tokens
        span.cost = cost
        self._finish(span)

    @contextmanager
    def span(self, name: str, input: str = ""):
        """步骤级上下文：把 name 设为「当前 span」，with 块内开的子 span 自动挂到它下面。"""
        s = self.start_span(name, input=input)
        token = _current_span.set(s)
        try:
            yield s
        finally:
            _current_span.reset(token)
            self._finish(s)

    @property
    def roots(self) -> list[Span]:
        return [s for s in self.spans if s.parent is None]

    def render_tree(self) -> str:
        """把 Trace 树渲染成缩进文本（span 名 + 耗时 + token），便于肉眼定位最慢的一步。"""
        lines: list[str] = []

        def walk(span: Span, depth: int) -> None:
            lines.append("  " * depth + f"{span.name} ({span.duration:.3f}s, {span.tokens}t)")
            for c in span.children:
                walk(c, depth + 1)

        for r in self.roots:
            walk(r, 0)
        return "\n".join(lines)

    def summary_by_name(self) -> dict[str, dict]:
        """按 span name 聚合：次数/总耗时/总 token（回答「哪一步最慢/最费」）。"""
        agg: dict[str, dict] = {}
        for s in self.spans:
            a = agg.setdefault(s.name, {"count": 0, "duration": 0.0, "tokens": 0})
            a["count"] += 1
            a["duration"] += s.duration
            a["tokens"] += s.tokens
        return agg

    def root_duration(self) -> float:
        """根 span 总耗时 = 真实墙钟时间（子 span 与父 span 时间重叠，不能相加）。"""
        return sum(s.duration for s in self.roots)

    def total_tokens(self) -> int:
        return sum(s.tokens for s in self.spans)

    def total_cost(self) -> float:
        return sum(s.cost for s in self.spans)

    def total_duration(self) -> float:
        """所有 span 耗时之和（含嵌套，会重复计；精确墙钟用 root_duration()）。"""
        return sum(s.duration for s in self.spans)


class LangfuseBackend:
    """Langfuse 上报后端：惰性导入，未配置 key 则 no-op（不阻塞主流程）。"""

    def __init__(self, public_key: str | None = None, secret_key: str | None = None,
                 host: str | None = None):
        self._client = None
        if public_key and secret_key:
            from langfuse import Langfuse  # 惰性导入，避免测试环境硬依赖
            self._client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)

    def record(self, span: Span) -> None:
        if self._client is None:
            return  # 未配置，静默跳过
        # Langfuse generation：把 span 记成一次 LLM 生成（usage 简化为 output token）
        self._client.generation(
            name=span.name,
            input=span.input,
            output=span.output,
            usage={"input": 0, "output": span.tokens, "total": span.tokens},
        )


def trace_step(tracer, name: str):
    """给节点/步骤函数包一层 span；tracer 为 None 时原样透传（测试/无监控环境零开销）。"""

    def decorator(fn):
        def wrapped(*args, **kwargs):
            if tracer is None:
                return fn(*args, **kwargs)
            with tracer.span(name):
                return fn(*args, **kwargs)
        return wrapped

    return decorator

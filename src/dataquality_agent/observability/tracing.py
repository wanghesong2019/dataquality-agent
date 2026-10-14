"""可观测：Trace + 成本台账。默认记录到内存（测试/本地），配 Langfuse 后上报。

知识地图（为什么需要它）
--------------------------
回答"每次巡检跑了多少 Token、花了多少钱、哪一步最慢"。分两块：
- Trace：一次运行里发生了什么——每次 LLM 调用的输入/输出/token/耗时（`Span`）。
- 成本台账（`CostLedger`）：累计 token/成本/调用次数。

关键设计原则：可观测是"旁路"，不能因为监控挂了导致主流程挂。所以 `LangfuseBackend`
惰性导入 + 未配置 no-op；集成点 `LLMAdapter.__call__` 每次调用埋一个 span，token 计数
和 CostLedger 共用同一份（`len(prompt)+len(resp)`），两者永远对得上。
"""
import time
from dataclasses import dataclass, field


@dataclass
class Span:
    """一次 LLM 调用（或一个阶段）的观测记录。"""

    name: str
    start: float
    input: str = ""
    output: str = ""
    tokens: int = 0
    cost: float = 0.0
    end: float = 0.0

    @property
    def duration(self) -> float:
        return self.end - self.start


class Tracer:
    """记录 pipeline 运行 + 每次 LLM 调用。backend 可插拔（Langfuse / 内存），默认只记内存。"""

    def __init__(self, backend=None):
        self.backend = backend
        self.spans: list[Span] = []

    def start_span(self, name: str, input: str = "") -> Span:
        span = Span(name=name, start=time.time(), input=input)
        self.spans.append(span)
        return span

    def end_span(self, span: Span, output: str = "", tokens: int = 0, cost: float = 0.0) -> None:
        span.end = time.time()
        span.output = output
        span.tokens = tokens
        span.cost = cost
        if self.backend is not None:
            self.backend.record(span)

    def total_tokens(self) -> int:
        return sum(s.tokens for s in self.spans)

    def total_cost(self) -> float:
        return sum(s.cost for s in self.spans)


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

"""模型 adapter：可插拔 LLM 调用 + 重试护栏 + 成本台账 + function calling。"""
import os

from dataquality_agent.models import CostLedger


def _estimate_tokens(messages: list[dict], resp: dict) -> int:
    """Token 估算（按字符数）——仅当客户端不返回 usage 时兜底，非精确值。"""
    n = 0
    for m in messages:
        n += len(str(m.get("content", "")))
        for tc in m.get("tool_calls") or []:
            n += len(str(tc.get("function", {}).get("arguments", "")))
    n += len(str(resp.get("content", "")))
    for tc in resp.get("tool_calls") or []:
        n += len(str(tc.get("function", {}).get("arguments", "")))
    return n


def _count_tokens(messages: list[dict], resp: dict) -> int:
    """优先用 API 返回的 usage.total_tokens（真实计数），缺失时回退字符估算。"""
    total = (resp.get("usage") or {}).get("total_tokens")
    return total if total is not None else _estimate_tokens(messages, resp)


class LLMAdapter:
    """统一模型调用入口：所有 agent 都通过它调模型，统一重试 + 计成本 + trace。

    客户端接口：`client.chat(messages, tools=None, tool_choice=None, response_format=None) -> dict`，
    返回 OpenAI 风格的 assistant message（`{content, tool_calls, usage}`）；usage 为真实 token 计数，缺失时按字符估算兜底。
    """

    def __init__(self, client, cost_ledger: CostLedger | None = None, tracer=None):
        self.client = client
        self.cost_ledger = cost_ledger or CostLedger()
        self.tracer = tracer  # 可观测 Trace（Tracer），None 则不追踪

    def __call__(self, prompt: str, max_retries: int = 2) -> str:
        """文本调用（单 user message），返回纯文本。兼容简单场景（如报告 agent）。"""
        resp = self.chat([{"role": "user", "content": prompt}], max_retries=max_retries)
        return resp.get("content") or ""

    def chat(self, messages: list[dict], tools=None, tool_choice=None,
             response_format=None, max_retries: int = 2) -> dict:
        """带重试 + 成本 + trace 的 chat 调用，返回 assistant message dict。"""
        span = self.tracer.start_span("llm", input=str(messages)) if self.tracer else None
        for attempt in range(max_retries + 1):
            try:
                resp = self.client.chat(messages, tools=tools, tool_choice=tool_choice,
                                        response_format=response_format)
            except Exception:
                if attempt == max_retries:
                    raise
                continue  # 重试
            self.cost_ledger.llm_calls += 1
            tokens = _count_tokens(messages, resp)
            self.cost_ledger.total_tokens += tokens
            if span is not None:
                self.tracer.end_span(span, output=str(resp), tokens=tokens)
            return resp
        raise RuntimeError("unreachable")


class DeepSeekClient:
    """DeepSeek API 客户端（OpenAI 兼容），支持 function calling + 结构化输出。

    chat(messages, tools, tool_choice, response_format) -> {content, tool_calls, usage}
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")

    def chat(self, messages: list[dict], tools=None, tool_choice=None,
             response_format=None) -> dict:
        import requests  # 延迟导入，避免测试环境硬依赖

        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not set")
        payload = {"model": "deepseek-chat", "messages": messages}
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
        if response_format:
            payload["response_format"] = response_format
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        return {
            "content": msg.get("content") or "",
            "tool_calls": msg.get("tool_calls") or [],
            "usage": data.get("usage") or {},
        }

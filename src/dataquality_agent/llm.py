"""模型 adapter：可插拔 LLM 调用 + 重试护栏 + 成本台账。"""
import os

from dataquality_agent.models import CostLedger


class LLMAdapter:
    """统一模型调用入口：所有 agent 都通过它调模型，统一重试 + 计成本。"""

    def __init__(self, client, cost_ledger: CostLedger | None = None, tracer=None):
        self.client = client  # 有 .chat(prompt) -> str 的客户端
        self.cost_ledger = cost_ledger or CostLedger()
        self.tracer = tracer  # 可观测 Trace（Tracer），None 则不追踪

    def __call__(self, prompt: str, max_retries: int = 2) -> str:
        span = self.tracer.start_span("llm", input=prompt) if self.tracer else None
        for attempt in range(max_retries + 1):
            try:
                resp = self.client.chat(prompt)
            except Exception:
                if attempt == max_retries:
                    raise
                continue  # 重试
            self.cost_ledger.llm_calls += 1
            # 粗略 Token 估算（按字符数，生产应换成 tokenizer 精确统计）
            tokens = len(prompt) + len(resp)
            self.cost_ledger.total_tokens += tokens
            if span is not None:
                self.tracer.end_span(span, output=resp, tokens=tokens)
            return resp
        raise RuntimeError("unreachable")


class DeepSeekClient:
    """DeepSeek API 客户端（OpenAI 兼容）。生产用，需要环境变量 DEEPSEEK_API_KEY。"""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")

    def chat(self, prompt: str) -> str:
        import requests  # 延迟导入，避免测试环境硬依赖

        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not set")
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

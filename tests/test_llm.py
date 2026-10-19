import pytest

from dataquality_agent.llm import DeepSeekClient, LLMAdapter


def _msg(content="ok", tool_calls=None):
    return {"content": content, "tool_calls": tool_calls or []}


def test_llm_adapter_retries_on_failure():
    calls = {"n": 0}

    class FakeClient:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("temporary")
            return _msg("ok")

    adapter = LLMAdapter(FakeClient())
    assert adapter("hello") == "ok"
    assert calls["n"] == 2  # 失败一次后重试成功


def test_llm_adapter_gives_up_after_max_retries():
    class AlwaysFail:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            raise ValueError("always")

    adapter = LLMAdapter(AlwaysFail())
    with pytest.raises(ValueError):
        adapter("hello", max_retries=2)


def test_llm_adapter_tracks_cost():
    class FakeClient:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return _msg("ok")

    adapter = LLMAdapter(FakeClient())
    adapter("hello world")
    assert adapter.cost_ledger.llm_calls == 1
    assert adapter.cost_ledger.total_tokens > 0


def test_llm_adapter_uses_real_usage_when_present():
    class FakeClient:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return {"content": "ok", "tool_calls": [],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105}}

    adapter = LLMAdapter(FakeClient())
    adapter("hello")
    assert adapter.cost_ledger.total_tokens == 105


def test_llm_adapter_emits_trace():
    from dataquality_agent.observability.tracing import Tracer

    class FakeClient:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            return _msg("ok")

    tracer = Tracer()
    adapter = LLMAdapter(FakeClient(), tracer=tracer)
    adapter("hi")
    assert len(tracer.spans) == 1
    assert tracer.spans[0].tokens == len("hi") + len("ok")


def test_llm_adapter_chat_passes_tools_and_tool_choice():
    captured = {}

    class FakeClient:
        def chat(self, messages, tools=None, tool_choice=None, response_format=None):
            captured["tools"] = tools
            captured["tool_choice"] = tool_choice
            return _msg("", [{"id": "1", "function": {"name": "f", "arguments": "{}"}}])

    adapter = LLMAdapter(FakeClient())
    tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
    tc = {"type": "function", "function": {"name": "f"}}
    resp = adapter.chat([{"role": "user", "content": "hi"}], tools=tools, tool_choice=tc)
    assert captured["tools"] == tools
    assert captured["tool_choice"] == tc
    assert resp["tool_calls"][0]["function"]["name"] == "f"


def test_deepseek_client_builds_payload(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            }

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return FakeResp()

    monkeypatch.setattr("requests.post", fake_post)
    c = DeepSeekClient(api_key="sk-test")
    resp = c.chat([{"role": "user", "content": "hi"}],
                  tools=[{"type": "function", "function": {"name": "f", "parameters": {}}}],
                  tool_choice={"type": "function", "function": {"name": "f"}})
    assert captured["json"]["model"] == "deepseek-chat"
    assert captured["json"]["tools"][0]["function"]["name"] == "f"
    assert captured["json"]["tool_choice"]["function"]["name"] == "f"
    assert resp == {
        "content": "ok",
        "tool_calls": [],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }

"""FakeLLM: the real LLMClient over a scripted fake OpenAI SDK, so JSON repair, cache, budget and the
circuit breaker are exercised without network calls."""
import json
from types import SimpleNamespace

from src.services.llm_client import LLMClient
from src.utils.config import Settings


class _Completions:
    def __init__(self, script):
        self.script, self.calls = script, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("FakeLLM script exhausted")
        item = self.script.pop(0)
        if callable(item):
            item = item(kwargs)
        if isinstance(item, Exception):
            raise item
        content = item if isinstance(item, str) else json.dumps(item)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
                               usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50))


class FakeLLM(LLMClient):
    """script: replies in order; each a dict (JSON), str (raw text), Exception, or callable(kwargs) -> one of those."""

    def __init__(self, script=None, cache_path=None, **overrides):
        settings = Settings(_env_file=None, llm_provider="none", llm_rpm_limit=1000, **overrides)
        super().__init__(settings, cache_path=cache_path, model="fake-model")
        self.completions = _Completions(list(script or []))
        self._client = SimpleNamespace(chat=SimpleNamespace(completions=self.completions))

    @property
    def calls(self) -> list[dict]:
        return self.completions.calls


def openai_error(cls_name: str, status: int):
    """Build an openai SDK exception (AuthenticationError, RateLimitError, ...) without a network response."""
    import httpx
    import openai
    request = httpx.Request("POST", "https://fake/v1/chat/completions")
    if cls_name == "APITimeoutError":
        return openai.APITimeoutError(request=request)
    response = httpx.Response(status, request=request)
    return getattr(openai, cls_name)(f"fake {status}", response=response, body=None)


# ---------------------------------------------------------------------------- Anthropic provider (2026-10-09)
class _Messages:
    """Scripted Anthropic `messages.create`. Items as for FakeLLM; a SimpleNamespace is returned as the response."""

    def __init__(self, script, calls):
        self.script, self.calls = script, calls

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("FakeAnthropicLLM script exhausted")
        item = self.script.pop(0)
        if callable(item):
            item = item(kwargs)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, SimpleNamespace):
            return item
        return anthropic_message(item if isinstance(item, str) else json.dumps(item))


def anthropic_message(text, stop_reason="end_turn", thinking=True, category=None, cache_read=0):
    content = ([SimpleNamespace(type="thinking", thinking="", signature="sig")] if thinking else [])
    content += [SimpleNamespace(type="text", text=text)] if text else []
    return SimpleNamespace(content=content, stop_reason=stop_reason,
                           stop_details=SimpleNamespace(type="refusal", category=category) if category else None,
                           usage=SimpleNamespace(input_tokens=100 - cache_read, output_tokens=50,
                                                 cache_creation_input_tokens=0, cache_read_input_tokens=cache_read))


class FakeAnthropicLLM(LLMClient):
    """The real LLMClient on its Anthropic path over a scripted fake Anthropic SDK (messages and beta.messages)."""

    def __init__(self, script=None, cache_path=None, spend_ledger=None, **overrides):
        settings = Settings(_env_file=None, llm_provider="none", llm_rpm_limit=1000, **overrides)
        super().__init__(settings, cache_path=cache_path, model="claude-sonnet-5-5", spend_ledger=spend_ledger)
        self.provider, self.calls = "anthropic", []
        messages = _Messages(list(script or []), self.calls)
        self._client = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))


def anthropic_error(cls_name: str, status: int):
    """Build an anthropic SDK exception without a network response."""
    import anthropic
    import httpx2
    request = httpx2.Request("POST", "https://fake/v1/messages")
    if cls_name == "APITimeoutError":
        return anthropic.APITimeoutError(request=request)
    response = httpx2.Response(status, request=request, headers={"retry-after": "7"})
    return getattr(anthropic, cls_name)(f"fake {status}", response=response, body=None)

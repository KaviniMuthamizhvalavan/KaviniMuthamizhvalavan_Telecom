"""Anthropic provider (2026-10-09 migration): request shape, response parsing, token accounting, errors, cache and the
graph end to end, all through the real LLMClient over a scripted fake Anthropic SDK. NVIDIA stays the rollback."""
import hashlib
import json

import pytest
from pydantic import BaseModel

from src.services.llm_client import LLMError, LLMUnavailable, StructuredOutputError
from src.utils.config import Settings
from tests.fakes import FakeAnthropicLLM, FakeLLM, anthropic_error, anthropic_message
from tests.test_agents_graph import Router, container, run  # noqa: F401 (container is a fixture)


class Out(BaseModel):
    category: str
    confidence: float


MSG = [{"role": "system", "content": "You are the classifier."}, {"role": "user", "content": "classify this"}]
GOOD = {"category": "TRANSPORT_QOS", "confidence": 0.9}


def test_direct_claude_settings_and_nvidia_is_the_rollback():
    s = Settings(_env_file=None, llm_provider="anthropic", anthropic_api_key="k")
    assert s.runtime_model == "claude-haiku-5-5" and s.llm_configured
    assert not Settings(_env_file=None, llm_provider="anthropic", llm_api_key="nv").llm_configured  # no Claude key
    nv = Settings(_env_file=None, llm_provider="openai_compatible", llm_api_key="nv", anthropic_api_key="k")
    assert nv.llm_configured and nv.runtime_model == "nvidia/nemotron-3-super-120b-a12b"


def test_request_shape_reasoning_on():
    llm = FakeAnthropicLLM([GOOD])
    llm.generate_json(MSG, Out, max_tokens=100, reasoning=True, reasoning_allowance=4096)
    kw = llm.calls[0]
    assert kw["model"] == "claude-sonnet-5-5" and kw["max_tokens"] == 100 + 4096
    assert kw["system"].startswith("Respond with a single JSON object") and kw["system"].endswith("You are the classifier.")
    assert kw["messages"] == [{"role": "user", "content": "classify this"}]  # no system role inside messages
    assert kw["thinking"] == {"type": "adaptive"} and kw["output_config"] == {"effort": "medium"}
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"
    for openai_only in ("temperature", "response_format", "extra_body"):
        assert openai_only not in kw


def test_request_shape_reasoning_off_and_fallback_disabled():
    llm = FakeAnthropicLLM([GOOD], anthropic_refusal_fallback=False)
    llm.generate_json(MSG, Out, max_tokens=100, reasoning=False)
    kw = llm.calls[0]
    assert kw["thinking"] == {"type": "between_tools"} and kw["output_config"] == {"effort": "low"}
    assert kw["max_tokens"] == 100 and "betas" not in kw and "fallbacks" not in kw


def test_text_blocks_parsed_thinking_skipped_and_cache_tokens_counted():
    reply = anthropic_message(json.dumps(GOOD), cache_read=40)
    reply.content.append(type(reply.content[0])(type="text", text=""))
    llm = FakeAnthropicLLM([reply])
    usage = llm.new_usage()
    assert llm.generate_json(MSG, Out, max_tokens=100, usage=usage).category == "TRANSPORT_QOS"
    assert usage.tokens_in == 100 and usage.tokens_out == 50  # 60 uncached + 40 cache read; output incl. thinking


def test_truncated_reply_goes_to_one_repair():
    llm = FakeAnthropicLLM([anthropic_message('{"category": "TRANS', stop_reason="max_tokens"), GOOD])
    usage = llm.new_usage()
    assert llm.generate_json(MSG, Out, max_tokens=100, usage=usage).category == "TRANSPORT_QOS"
    assert [c["purpose"] for c in usage.calls] == ["json", "json_repair"]
    assert llm.calls[1]["messages"][-1]["content"].startswith("That reply was invalid")
    assert [m["role"] for m in llm.calls[1]["messages"]] == ["user", "assistant", "user"]


def test_empty_reply_is_a_structured_output_error():
    llm = FakeAnthropicLLM([anthropic_message(""), anthropic_message("")])
    with pytest.raises(StructuredOutputError):
        llm.generate_json(MSG, Out, max_tokens=100)


def test_refusal_raises_llm_error_without_repair():
    llm = FakeAnthropicLLM([anthropic_message("", stop_reason="refusal", category="cyber")])
    usage = llm.new_usage()
    with pytest.raises(LLMError, match="declined.*cyber") as exc:
        llm.generate_json(MSG, Out, max_tokens=100, usage=usage)
    assert not isinstance(exc.value, StructuredOutputError)  # node fallback, not a repair call
    assert len(llm.calls) == 1 and usage.llm_calls == 1 and not llm.circuit.is_open


def test_auth_error_opens_circuit_until_restart():
    llm = FakeAnthropicLLM([anthropic_error("AuthenticationError", 401)])
    with pytest.raises(LLMUnavailable):
        llm.chat(MSG, max_tokens=10)
    assert not llm.available and llm.circuit.open_until == float("inf")


def test_rate_limits_report_retry_after_and_open_circuit():
    llm = FakeAnthropicLLM([anthropic_error("RateLimitError", 429)] * 3)
    for _ in range(3):
        with pytest.raises(LLMError, match="retry-after=7"):
            llm.chat(MSG, max_tokens=10, use_cache=False)
    assert llm.circuit.is_open


def test_overloaded_counts_as_server_failure_but_bad_request_does_not():
    llm = FakeAnthropicLLM([anthropic_error("OverloadedError", 529), anthropic_error("BadRequestError", 400)])
    with pytest.raises(LLMError, match="529"):
        llm.chat(MSG, max_tokens=10, use_cache=False)
    assert llm.circuit.consecutive == 1
    with pytest.raises(LLMError, match="400"):
        llm.chat(MSG, max_tokens=10, use_cache=False)
    assert llm.circuit.consecutive == 1 and not llm.circuit.is_open


def test_cache_hit_is_free_and_providers_never_share_entries(tmp_path):
    db = tmp_path / "c.db"
    claude = FakeAnthropicLLM([GOOD], cache_path=db)
    u1, u2 = claude.new_usage(), claude.new_usage()
    claude.generate_json(MSG, Out, max_tokens=100, usage=u1)
    claude.generate_json(MSG, Out, max_tokens=100, usage=u2)
    assert u1.llm_calls == 1 and u2.cached_calls == 1
    nvidia = FakeLLM([{"category": "NVIDIA", "confidence": 0.5}], cache_path=db)
    assert nvidia.generate_json(MSG, Out, max_tokens=100).category == "NVIDIA"  # not served Claude's reply


def test_nvidia_cache_key_is_unchanged(tmp_path):
    """The rollback path computes the same key as before the migration, so existing NVIDIA cache entries stay valid."""
    llm = FakeLLM(["hello"], cache_path=tmp_path / "c.db")
    llm.chat(MSG, max_tokens=10, prompt_version="v1", reasoning=False)
    params = {"model": "fake-model", "temperature": llm.s.llm_temperature, "max_tokens": 10}
    extra = {"chat_template_kwargs": {"enable_thinking": False}}
    key = hashlib.sha256(json.dumps([llm.s.llm_base_url, MSG, params, extra, "v1"], sort_keys=True).encode()).hexdigest()
    assert llm.cache.get(key)[0] == "hello"


def _openai_shaped(router):
    """Let the graph Router (written for OpenAI-shaped calls) answer Anthropic-shaped ones."""
    def answer(kwargs):
        return router({**kwargs, "messages": [{"role": "system", "content": kwargs["system"]},
                                              {"role": "system", "content": ""}, *kwargs["messages"]]})
    return answer


def test_graph_end_to_end_on_claude(container):
    router = Router()
    r = run(container, llm=FakeAnthropicLLM([_openai_shaped(router)] * 20, llm_cache_enabled=False))
    assert r["status"] == "ok" and r["validation"]["verdict"] == "pass" and r["meta"]["llm_calls"] == 4
    assert r["meta"]["model"] == "claude-sonnet-5-5" and r["meta"]["judge_model"] == "claude-sonnet-5-5"  # judge shares the client
    thinking = {role: kw["thinking"]["type"] for role, _, kw in router.seen}
    assert thinking == {"classifier": "between_tools", "analyst": "adaptive", "recommender": "between_tools",
                        "judge": "adaptive"}  # option B mapped to Claude

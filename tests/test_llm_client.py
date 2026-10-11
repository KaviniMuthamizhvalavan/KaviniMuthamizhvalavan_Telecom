"""LLM client contract: JSON + one repair, think-stripping, cache, run budget, LLM gate (circuit breaker)."""
import pytest
from pydantic import BaseModel

from src.services.llm_client import (CircuitBreaker, LLMBudgetExceeded, LLMError, LLMUnavailable,
                                     StructuredOutputError, extract_json, schema_hint)
from tests.fakes import FakeLLM, openai_error


class Out(BaseModel):
    category: str
    confidence: float


MSG = [{"role": "user", "content": "classify this"}]


def test_valid_json_first_try():
    llm = FakeLLM([{"category": "TRANSPORT_QOS", "confidence": 0.9}])
    usage = llm.new_usage()
    assert llm.generate_json(MSG, Out, max_tokens=100, usage=usage).category == "TRANSPORT_QOS"
    assert usage.llm_calls == 1 and usage.tokens_in == 100
    assert llm.calls[0]["response_format"] == {"type": "json_object"}
    assert "JSON schema" in llm.calls[0]["messages"][0]["content"]


def test_one_repair_then_success_and_then_failure():
    llm = FakeLLM(["not json at all", {"category": "X", "confidence": 0.5}])
    assert llm.generate_json(MSG, Out, max_tokens=100).category == "X"
    assert "invalid" in llm.calls[1]["messages"][-1]["content"]
    bad = FakeLLM(["nope", {"category": "X"}])  # repair still misses a required field
    with pytest.raises(StructuredOutputError):
        bad.generate_json(MSG, Out, max_tokens=100)
    assert len(bad.calls) == 2  # exactly one repair attempt


def test_think_blocks_and_fences_are_stripped():
    assert extract_json('<think>hmm {"a": 1}</think>\n```json\n{"category": "A", "confidence": 1}\n```') == \
        '{"category": "A", "confidence": 1}'


def test_cache_hit_is_free(tmp_path):
    llm = FakeLLM([{"category": "A", "confidence": 1}], cache_path=tmp_path / "c.db")
    u1, u2 = llm.new_usage(), llm.new_usage()
    llm.generate_json(MSG, Out, max_tokens=100, usage=u1)
    llm.generate_json(MSG, Out, max_tokens=100, usage=u2)  # script is empty: must come from cache
    assert u1.llm_calls == 1 and u2.llm_calls == 0 and u2.cached_calls == 1


def test_run_budget_aborts():
    llm = FakeLLM([{"category": "A", "confidence": 1}] * 3, max_llm_calls_per_run=2)
    usage = llm.new_usage()
    for _ in range(2):
        llm.chat(MSG, max_tokens=10, usage=usage, use_cache=False)
    with pytest.raises(LLMBudgetExceeded):
        llm.chat(MSG, max_tokens=10, usage=usage, use_cache=False)


def test_auth_error_opens_circuit_until_restart():
    llm = FakeLLM([openai_error("AuthenticationError", 401)])
    assert llm.available and llm.circuit.reachable is None
    with pytest.raises(LLMUnavailable):
        llm.chat(MSG, max_tokens=10)
    assert not llm.available and llm.circuit.reachable is False
    with pytest.raises(LLMUnavailable):  # fails fast, no further provider call
        llm.chat(MSG, max_tokens=10)
    assert len(llm.calls) == 1


def test_three_rate_limits_open_circuit_then_cooldown_recovers(monkeypatch):
    """Deterministic: a fake monotonic clock that only moves when the test moves it (a real 50 ms cooldown was flaky
    because slow calls could outlast it before the 'still open' assertion)."""
    from src.services import llm_client
    now = [1000.0]
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: now[0])
    llm = FakeLLM([openai_error("RateLimitError", 429)] * 2 + [openai_error("APITimeoutError", 0)] +
                  ["ok"])
    llm.circuit = CircuitBreaker(cooldown_s=300)
    for _ in range(3):
        with pytest.raises(LLMError):
            llm.chat(MSG, max_tokens=10, use_cache=False)
    assert not llm.available
    now[0] += 299.9
    assert not llm.available  # still open just before the cooldown ends
    now[0] += 0.1
    assert llm.available  # half-open after the cooldown
    assert llm.chat(MSG, max_tokens=10, use_cache=False) == "ok" and llm.circuit.reachable is True


def test_reasoning_allowance_added_to_max_tokens():
    llm = FakeLLM(["ok"], llm_reasoning=True, llm_reasoning_allowance=1024)
    llm.chat(MSG, max_tokens=400, use_cache=False)
    assert llm.calls[0]["max_tokens"] == 1424


def test_per_call_reasoning_allowance_overrides_default():
    llm = FakeLLM(["ok", "ok"], llm_reasoning=True, llm_reasoning_allowance=2048)
    llm.chat(MSG, max_tokens=900, use_cache=False, reasoning_allowance=4096)
    llm.chat(MSG, max_tokens=900, use_cache=False, reasoning=False, reasoning_allowance=4096)
    assert [c["max_tokens"] for c in llm.calls] == [4996, 900]


def test_invalid_reply_is_never_cached(tmp_path):
    """Backend investigation 2026-10-07: a malformed reply was cached and would be replayed on identical requests."""
    llm = FakeLLM([{"category": "A"}, {"category": "A", "confidence": 0.9}], cache_path=tmp_path / "c.db")
    assert llm.generate_json(MSG, Out, max_tokens=10).confidence == 0.9  # invalid first reply -> repair succeeds
    with llm.cache._conn() as con:
        assert con.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0  # invalid reply not cached
    ok = FakeLLM([{"category": "A", "confidence": 0.9}], cache_path=tmp_path / "c.db")
    ok.generate_json(MSG, Out, max_tokens=10)
    usage = ok.new_usage()
    ok.generate_json(MSG, Out, max_tokens=10, usage=usage)  # valid replies are still cached
    assert usage.cached_calls == 1 and usage.llm_calls == 0


def test_cached_reply_failing_validation_is_evicted(tmp_path):
    good = {"category": "A", "confidence": 0.9}
    llm = FakeLLM([{"category": "A"}], cache_path=tmp_path / "c.db")
    # simulate a pre-fix cache: chat() without a validator caches the garbled reply under the real key
    system = {"role": "system", "content": "Respond with a single JSON object only, no prose, matching this JSON "
                                           f"schema:\n{schema_hint(Out)}"}
    llm.chat([system, *MSG], max_tokens=10, json_mode=True)
    llm.completions.script = [good]
    usage = llm.new_usage()
    assert llm.generate_json(MSG, Out, max_tokens=10, usage=usage).confidence == 0.9
    assert usage.cached_calls == 0 and usage.llm_calls == 1  # the poisoned entry was not replayed

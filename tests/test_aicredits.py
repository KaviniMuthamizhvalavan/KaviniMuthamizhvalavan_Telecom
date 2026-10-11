"""AICredits provider (2026-10-10): Claude Haiku 5.5 through the OpenAI-compatible AICredits gateway is the default
runtime for development and testing, and openai/gpt-oss-120b through AICredits is the default evaluation judge (a
different model family from the agents). Fake transports only; every ledger and cache lives in tmp_path."""
from types import SimpleNamespace

import pytest

from src.services.llm_client import (AICREDITS_INR_PER_USD, LLMClient, LLMUnavailable, SpendLedger,
                                     aicredits_cost_usd)
from src.utils.config import Settings
from tests.fakes import FakeLLM, _Completions, openai_error

MSG = [{"role": "system", "content": "You are the classifier."}, {"role": "user", "content": "classify this"}]


def aicredits_llm(tmp_path, script, model=None, **kw) -> LLMClient:
    s = Settings(_env_file=None, aicredits_api_key="test-aicredits", artifacts_dir=tmp_path, llm_rpm_limit=1000,
                 **{"llm_cache_enabled": False, **kw})
    llm = LLMClient(s, cache_path=tmp_path / "cache.db", model=model)
    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions(list(script))))
    return llm


def calls(llm):
    return llm._client.chat.completions.calls


def test_defaults_are_aicredits_haiku_runtime_and_gpt_oss_judge():
    s = Settings(_env_file=None, aicredits_api_key="k")
    assert (s.llm_provider, s.runtime_model, s.runtime_base_url) == \
        ("aicredits", "anthropic/claude-haiku-5.5", "https://api.aicredits.in/v1")
    assert s.llm_configured and not Settings(_env_file=None, anthropic_api_key="k").llm_configured
    es = s.eval_settings()
    assert (es.llm_provider, es.runtime_model, es.aicredits_api_key) == ("aicredits", "openai/gpt-oss-120b", "k")


def test_real_client_targets_the_gateway_and_keeps_a_ledger(tmp_path):
    llm = LLMClient(Settings(_env_file=None, aicredits_api_key="k", artifacts_dir=tmp_path))
    assert str(llm._client.base_url).rstrip("/") == "https://api.aicredits.in/v1"
    assert llm.spend_ledger.path == tmp_path / "llm_spend.db"


def test_claude_request_shape_has_no_nvidia_options_and_no_temperature(tmp_path):
    llm = aicredits_llm(tmp_path, ['{"a": 1}'])
    llm.chat(MSG, max_tokens=100, json_mode=True, reasoning=False)
    kw = calls(llm)[0]
    assert kw["model"] == "anthropic/claude-haiku-5.5" and kw["response_format"] == {"type": "json_object"}
    assert kw["extra_body"] is None and "temperature" not in kw  # no chat_template_kwargs; Claude: default sampling
    assert kw["messages"] == MSG
    assert kw["max_tokens"] == 100 + 2048  # thinking cannot be switched off via the gateway: allowance always reserved


def test_agent_allowance_is_used_when_given(tmp_path):
    llm = aicredits_llm(tmp_path, ["ok"])
    llm.chat(MSG, max_tokens=900, reasoning=True, reasoning_allowance=4096)
    assert calls(llm)[0]["max_tokens"] == 900 + 4096


def test_gpt_oss_request_keeps_temperature(tmp_path):
    llm = aicredits_llm(tmp_path, ["ok"], model="openai/gpt-oss-120b")
    llm.chat(MSG, max_tokens=50)
    assert calls(llm)[0]["temperature"] == 0.1 and calls(llm)[0]["extra_body"] is None


def test_cost_is_recorded_in_usd_and_cache_hits_are_free(tmp_path):
    llm = aicredits_llm(tmp_path, ["ok"], llm_cache_enabled=True)
    llm.spend_ledger = SpendLedger(tmp_path / "spend.db")
    llm.chat(MSG, max_tokens=50)
    llm.chat(MSG, max_tokens=50)  # identical: served from the cache
    expected = (100 * 10.17 + 50 * 50.86) / 1e6 / AICREDITS_INR_PER_USD  # FakeLLM usage: 100 in, 50 out
    assert llm.spend_ledger.today() == pytest.approx(expected) and len(calls(llm)) == 1


def test_unknown_gateway_model_is_priced_at_the_top_tier():
    assert aicredits_cost_usd("someone/new-model", 1_000_000, 0) == pytest.approx(1525.66 / AICREDITS_INR_PER_USD)


def test_spend_cap_also_stops_gateway_calls(tmp_path):
    llm = aicredits_llm(tmp_path, ["ok"], llm_daily_budget_usd=0.01)
    llm.spend_ledger = SpendLedger(tmp_path / "spend.db")
    llm.spend_ledger.add("anthropic/claude-haiku-5.5", 0.01)
    with pytest.raises(LLMUnavailable, match="spend cap"):
        llm.chat(MSG, max_tokens=50)
    assert calls(llm) == []


def test_exhausted_credits_stop_calls_until_restart(tmp_path):
    llm = aicredits_llm(tmp_path, [openai_error("APIStatusError", 402)])
    with pytest.raises(LLMUnavailable, match="credits exhausted"):
        llm.chat(MSG, max_tokens=50)
    assert not llm.available and llm.circuit.open_until == float("inf")


def test_gateway_and_nvidia_never_share_cache_entries(tmp_path):
    db = tmp_path / "shared.db"
    gateway = aicredits_llm(tmp_path, ["from aicredits"], llm_cache_enabled=True, model="openai/gpt-oss-120b")
    gateway.cache = type(gateway.cache)(db) if gateway.cache else None
    gateway.chat(MSG, max_tokens=50)
    nvidia = FakeLLM(["from nvidia"], cache_path=db)
    nvidia.model = "openai/gpt-oss-120b"
    assert nvidia.chat(MSG, max_tokens=50) == "from nvidia"


def test_eval_judge_defaults_to_gpt_oss_on_aicredits(monkeypatch, tmp_path):
    from evaluation import deepeval_judge
    monkeypatch.setattr(deepeval_judge, "get_settings",  # tmp artifacts: the judge's ledger must not be the real one
                        lambda: Settings(_env_file=None, aicredits_api_key="k", artifacts_dir=tmp_path))
    judge = deepeval_judge.OpenAICompatibleJudge(use_cache=False)
    assert judge.llm.provider == "aicredits" and judge.get_model_name() == "openai/gpt-oss-120b"
    judge.llm._client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions(["  verdict  "])))
    judge.llm.spend_ledger = None
    assert judge.generate("score this") == "verdict"
    kw = judge.llm._client.chat.completions.calls[0]
    assert kw["model"] == "openai/gpt-oss-120b"
    assert kw["max_tokens"] == deepeval_judge.MAX_TOKENS + deepeval_judge.REASONING_ALLOWANCE

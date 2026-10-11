"""Daily API spend cap (2026-10-09): estimated cost per Claude call, a shared ledger, and the reduced (no-LLM) path once
LLM_DAILY_BUDGET_USD is reached. Fake transports only; every ledger lives in tmp_path, never in the real artifacts."""
import pytest

from src.services.llm_client import LLMClient, LLMUnavailable, SpendLedger, call_cost_usd
from src.utils.config import Settings
from tests.fakes import FakeAnthropicLLM, anthropic_message
from tests.test_agents_graph import Router, container, run  # noqa: F401 (container is a fixture)
from tests.test_llm_anthropic import _openai_shaped

MSG = [{"role": "user", "content": "x"}]


def test_default_daily_budget_is_one_dollar():
    assert Settings(_env_file=None).llm_daily_budget_usd == 1.0


@pytest.mark.parametrize("model, expected", [
    ("claude-haiku-5-5", (15_800 * 0.10 + 4_450 * 0.50) / 1e6),    # one measured /troubleshoot run's tokens
    ("claude-sonnet-5-5", (15_800 * 2.0 + 4_450 * 10.0) / 1e6),
    ("claude-opus-5-5", (15_800 * 4.0 + 4_450 * 20.0) / 1e6),
    ("some-future-model", (15_800 * 10.0 + 4_450 * 50.0) / 1e6),  # unknown: priced at the top tier
])
def test_cost_per_call(model, expected):
    assert call_cost_usd(model, 15_800, 0, 0, 4_450) == pytest.approx(expected)


def test_cache_tokens_and_haiku_long_prompt_tier():
    assert call_cost_usd("claude-sonnet-5-5", 0, 1_000_000, 1_000_000, 0) == pytest.approx(2.5 + 0.10)
    assert call_cost_usd("claude-haiku-5-5", 100_001, 0, 0, 1_000_000) == pytest.approx(0.0500005 + 2.50)


def test_ledger_accumulates_per_day_and_model(tmp_path, monkeypatch):
    ledger = SpendLedger(tmp_path / "spend.db")
    ledger.add("claude-haiku-5-5", 0.01)
    ledger.add("claude-haiku-5-5", 0.02)
    ledger.add("claude-sonnet-5-5", 0.10)
    assert ledger.today() == pytest.approx(0.13)
    assert {(m, n) for _, m, n, _ in ledger.report()} == {("claude-haiku-5-5", 2), ("claude-sonnet-5-5", 1)}
    monkeypatch.setattr(SpendLedger, "day", staticmethod(lambda: "2999-01-01"))
    assert ledger.today() == 0.0  # a new UTC day starts from zero


def test_each_call_is_recorded_and_cache_hits_are_free(tmp_path):
    ledger = SpendLedger(tmp_path / "spend.db")
    llm = FakeAnthropicLLM(["ok"], cache_path=tmp_path / "c.db", spend_ledger=ledger)
    llm.chat(MSG, max_tokens=10)
    llm.chat(MSG, max_tokens=10)  # identical request: served from the response cache
    assert ledger.today() == pytest.approx(call_cost_usd("claude-sonnet-5-5", 100, 0, 0, 50))
    assert ledger.report()[0][2] == 1


def test_refusals_are_recorded_too(tmp_path):
    ledger = SpendLedger(tmp_path / "spend.db")
    llm = FakeAnthropicLLM([anthropic_message("", stop_reason="refusal", category="cyber")], spend_ledger=ledger)
    with pytest.raises(Exception):
        llm.chat(MSG, max_tokens=10, use_cache=False)
    assert ledger.today() > 0


def test_cap_reached_closes_the_gate_and_refuses_calls(tmp_path):
    ledger = SpendLedger(tmp_path / "spend.db")
    ledger.add("claude-haiku-5-5", 0.50)
    llm = FakeAnthropicLLM(["ok"], spend_ledger=ledger, llm_daily_budget_usd=0.50)
    assert llm.spend_cap_reached and not llm.available
    with pytest.raises(LLMUnavailable, match="spend cap of \\$0.50"):
        llm.chat(MSG, max_tokens=10, use_cache=False)
    assert llm.calls == []  # nothing was sent


def test_graph_takes_the_reduced_path_when_the_cap_is_reached(container, tmp_path):
    ledger = SpendLedger(tmp_path / "spend.db")
    ledger.add("claude-haiku-5-5", 1.0)
    router = Router()
    r = run(container, llm=FakeAnthropicLLM([_openai_shaped(router)] * 20, llm_cache_enabled=False,
                                            spend_ledger=ledger))
    assert router.seen == [] and r["meta"]["llm_calls"] == 0  # no API call at all
    assert r["status"] == "degraded" and r["recommendations"]  # the deterministic answer is still returned


def test_real_claude_client_keeps_its_ledger_in_artifacts_dir(tmp_path):
    s = Settings(_env_file=None, llm_provider="anthropic", anthropic_api_key="k", artifacts_dir=tmp_path,
                 llm_cache_enabled=False)
    assert LLMClient(s).spend_ledger.path == tmp_path / "llm_spend.db"
    nvidia = Settings(_env_file=None, llm_provider="openai_compatible", llm_api_key="nv", artifacts_dir=tmp_path)
    assert LLMClient(nvidia).spend_ledger is None  # NVIDIA rollback is the free tier

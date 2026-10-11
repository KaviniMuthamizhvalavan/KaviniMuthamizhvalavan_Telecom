"""Which model each component uses (2026-10-09): every runtime agent, including the runtime judge, runs on Claude
Haiku 5.5 (Sonnet 5.5 before the cost change); the independent evaluation judge runs on its own explicitly configured
model (default Claude Haiku 5.5). NVIDIA is only an explicit rollback. No network: clients are built with dummy keys
and fake transports."""
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.services.container import build_llm
from src.services.llm_client import LLMClient
from src.utils.config import Settings
from tests.fakes import _Messages


# A real-configured client creates its spend ledger and cache under artifacts_dir: keep both out of the real artifacts/.
SCRATCH_ARTIFACTS = Path(tempfile.mkdtemp(prefix="routing_artifacts_"))


def claude_settings(**kw) -> Settings:
    """Direct-Anthropic configuration (the default provider is AICredits since 2026-10-10; see test_aicredits.py)."""
    return Settings(_env_file=None, anthropic_api_key="test-anthropic", llm_api_key="test-nvidia",
                    **{"llm_cache_enabled": False, "artifacts_dir": SCRATCH_ARTIFACTS, "llm_provider": "anthropic",
                       "eval_llm_provider": "anthropic", "eval_llm_model": "claude-haiku-5-5", **kw})


def fake_transport(llm: LLMClient, script) -> list[dict]:
    calls = []
    messages = _Messages(list(script), calls)
    llm._client = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))
    llm.spend_ledger = None  # fake replies are not spend
    return calls


def test_direct_anthropic_runtime_is_haiku_5_5_and_never_builds_an_openai_client():
    llm = build_llm(claude_settings())
    assert llm.provider == "anthropic" and llm.model == "claude-haiku-5-5"
    assert type(llm._client).__module__.startswith("anthropic")


def test_runtime_judge_is_claude_with_its_reasoning_setting():
    """No JUDGE_LLM_MODEL: the graph's judge uses the runtime client (graph._judge_llm). Its call is reasoning ON."""
    from src.agents.graph import _judge_llm
    llm = build_llm(claude_settings())
    assert _judge_llm(SimpleNamespace(judge_llm=None, llm=llm)) is llm
    calls = fake_transport(llm, ["{}"])
    llm.chat([{"role": "user", "content": "x"}], max_tokens=500, reasoning=llm.s.judge_reasoning,
             reasoning_allowance=llm.s.agent_reasoning_allowance)
    assert calls[0]["model"] == "claude-haiku-5-5" and calls[0]["thinking"] == {"type": "adaptive"}
    assert calls[0]["output_config"] == {"effort": "medium"} and calls[0]["max_tokens"] == 500 + 4096


def test_option_b_reasoning_settings_are_unchanged():
    s = claude_settings()
    assert (s.classifier_reasoning, s.analyst_reasoning, s.recommender_reasoning, s.judge_reasoning) == \
        (False, True, False, True)


def test_explicit_runtime_judge_model_stays_on_claude():
    s = claude_settings(judge_llm_model="claude-opus-5-5")
    judge = LLMClient(s, model=s.judge_llm_model)  # as ServiceContainer.build does
    assert judge.provider == "anthropic" and judge.model == "claude-opus-5-5"


def test_zero_key_mode_reports_no_model():
    assert Settings(_env_file=None, llm_provider="none").runtime_model == "none"


def test_nvidia_runtime_only_when_explicitly_selected():
    llm = build_llm(claude_settings(llm_provider="openai_compatible"))
    assert llm.provider == "openai_compatible" and llm.model == "nvidia/nemotron-3-super-120b-a12b"


def test_anthropic_eval_settings_use_haiku_5_5_separately_from_runtime():
    s = claude_settings()
    es = s.eval_settings()
    assert (s.eval_model, es.llm_provider, es.runtime_model, es.anthropic_effort_reasoning) == \
        ("claude-haiku-5-5", "anthropic", "claude-haiku-5-5", "medium")
    assert es.anthropic_api_key == "test-anthropic" and s.runtime_model == "claude-haiku-5-5"  # runtime untouched


def test_eval_settings_use_the_explicitly_configured_model_key_and_effort():
    es = claude_settings(eval_llm_model="claude-sonnet-5-5", eval_llm_api_key="eval-key", eval_llm_effort="high")
    out = es.eval_settings()
    assert (out.runtime_model, out.anthropic_api_key, out.anthropic_effort_reasoning) == \
        ("claude-sonnet-5-5", "eval-key", "high")


def test_eval_nvidia_rollback_is_explicit():
    es = claude_settings(eval_llm_provider="openai_compatible", eval_llm_model="openai/gpt-oss-20b").eval_settings()
    assert (es.llm_provider, es.runtime_model, es.llm_api_key) == ("openai_compatible", "openai/gpt-oss-20b",
                                                                   "test-nvidia")


def test_deepeval_judge_calls_the_configured_eval_model(monkeypatch):
    from evaluation import deepeval_judge
    monkeypatch.setattr(deepeval_judge, "get_settings", lambda: claude_settings())
    judge = deepeval_judge.OpenAICompatibleJudge(use_cache=False)
    assert judge.llm.provider == "anthropic" and judge.get_model_name() == "claude-haiku-5-5"
    calls = fake_transport(judge.llm, ["  verdict text  "])
    assert judge.generate("score this") == "verdict text"
    kw = calls[0]
    assert kw["model"] == "claude-haiku-5-5" and kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["max_tokens"] == deepeval_judge.MAX_TOKENS + deepeval_judge.REASONING_ALLOWANCE


@pytest.mark.parametrize("model, thinking", [("claude-sonnet-5-5", {"type": "between_tools"}),
                                             ("claude-haiku-5-5", {"type": "disabled"}),
                                             ("claude-opus-5-5", None)])
def test_reasoning_off_maps_per_model(model, thinking):
    """between_tools is Sonnet 5.5 only, Haiku 5.5 takes disabled; Opus 5.5 thinking cannot be disabled (no field)."""
    llm = LLMClient(claude_settings(), model=model)
    calls = fake_transport(llm, ["ok"])
    llm.chat([{"role": "user", "content": "x"}], max_tokens=50, reasoning=False)
    assert calls[0].get("thinking") == thinking and calls[0]["output_config"] == {"effort": "low"}

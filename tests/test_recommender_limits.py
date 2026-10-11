"""Recommender output limit on Claude (2026-10-09). The fixture is the complete G05 recommender reply from Claude Sonnet
5.5 (1,479 output tokens, 6 steps); the 1,400 cap cut it at 3,816 characters, inside step 6."""
import json
from pathlib import Path

import pytest

from src.agents import recommender_agent
from src.agents.recommender_agent import RecommenderOutput
from src.services.llm_client import StructuredOutputError
from tests.fakes import FakeAnthropicLLM, anthropic_message
from tests.test_agents_graph import Router, container, run  # noqa: F401 (container is a fixture)
from tests.test_llm_anthropic import _openai_shaped

REPLY = (Path(__file__).parent / "test_cases" / "claude_recommender_g05_reply.json").read_text(encoding="utf-8")
TRUNCATED_AT_1400 = REPLY[:3816]
MSG = [{"role": "system", "content": "You are the recommender."}, {"role": "user", "content": "weak signal"}]


def test_limit_covers_the_measured_reply_and_the_schema_maximum():
    assert recommender_agent.MAX_TOKENS == 2500  # measured 1,479 for 6 steps; 8 steps ~2,100


def test_complete_claude_reply_parses_with_actionable_steps():
    out = RecommenderOutput.model_validate_json(REPLY)
    assert len(out.recommendations) == 6 and out.escalation.needed
    assert all(r.verification.strip() and r.expected_kpi_effect.strip() and r.citations for r in out.recommendations)


def test_reply_truncated_at_the_old_cap_is_invalid():
    with pytest.raises(ValueError):
        RecommenderOutput.model_validate_json(TRUNCATED_AT_1400)


def test_truncated_reply_is_repaired():
    llm = FakeAnthropicLLM([anthropic_message(TRUNCATED_AT_1400, stop_reason="max_tokens", thinking=False),
                            anthropic_message(REPLY, thinking=False)])
    usage = llm.new_usage()
    out = llm.generate_json(MSG, RecommenderOutput, max_tokens=recommender_agent.MAX_TOKENS, usage=usage,
                            reasoning=False)
    assert len(out.recommendations) == 6 and [c["purpose"] for c in usage.calls] == ["json", "json_repair"]
    assert all(kw["max_tokens"] == 2500 for kw in llm.calls)


def test_truncated_twice_raises():
    llm = FakeAnthropicLLM([anthropic_message(TRUNCATED_AT_1400, stop_reason="max_tokens")] * 2)
    with pytest.raises(StructuredOutputError):
        llm.generate_json(MSG, RecommenderOutput, max_tokens=recommender_agent.MAX_TOKENS, reasoning=False)


class TruncatingRouter:
    """Graph Router on Anthropic-shaped calls; the recommender's first `n` calls come back truncated."""

    def __init__(self, n: int):
        self.router, self.n, self.recommender_kwargs = Router(), n, []
        self.answer = _openai_shaped(self.router)

    def __call__(self, kwargs):
        if "Troubleshooting Recommender" in kwargs["system"] and "independent reviewer" not in kwargs["system"]:
            self.recommender_kwargs.append(kwargs)
            if len(self.recommender_kwargs) <= self.n:
                return anthropic_message(TRUNCATED_AT_1400, stop_reason="max_tokens", thinking=False)
        return self.answer(kwargs)


def test_graph_recommender_uses_the_new_limit_and_recovers_from_one_truncation(container):
    router = TruncatingRouter(n=1)
    r = run(container, llm=FakeAnthropicLLM([router] * 20, llm_cache_enabled=False))
    assert r["status"] == "ok" and r["meta"]["llm_calls"] == 5  # 4 agents + 1 recommender repair
    assert [t["status"] for t in r["trace"] if t["node"] == "recommend"] == ["ok"]
    assert [(kw["max_tokens"], kw["thinking"]["type"]) for kw in router.recommender_kwargs] == [(2500, "between_tools")] * 2


def test_graph_falls_back_when_the_recommender_stays_truncated(container):
    router = TruncatingRouter(n=99)
    r = run(container, llm=FakeAnthropicLLM([router] * 20, llm_cache_enabled=False))
    assert r["status"] == "degraded" and ("recommend", "fallback") in [(t["node"], t["status"]) for t in r["trace"]]
    assert r["recommendations"] and any("recommender agent was unavailable" in w for w in r["warnings"])

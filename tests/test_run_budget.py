"""Per-run LLM budget (P1, 2026-10-09): call cap 12, token budget 50K. Exhaustion degrades per node, never errors.

Uses the scripted FakeLLM graph harness from test_agents_graph.py. Every FakeLLM call reports 150 tokens.
"""
from src.utils.config import get_settings
from tests.fakes import FakeLLM
from tests.test_agents_graph import BAD_SCORES, GOOD_SCORES, Router, container, run  # noqa: F401 (fixture)

GARBLED = {"garbled": True}  # valid JSON, wrong schema -> one repair attempt


class RepairRouter(Router):
    """Like Router, but the first call of every round for the listed roles returns a schema-invalid reply,
    so each such agent call costs one repair call (the Phase 11 G05 pattern)."""

    def __init__(self, garble_roles: set[str], **kw):
        super().__init__(**kw)
        self.garble_roles, self.pending = garble_roles, {}

    def __call__(self, kwargs):
        prompt = kwargs["messages"][0]["content"] + kwargs["messages"][1]["content"]
        is_repair = kwargs["messages"][-1]["content"].startswith("That reply was invalid")
        role = ("judge" if "independent reviewer" in prompt else "classifier" if "Network Incident Classification"
                in prompt else "analyst" if "Root-Cause & Impact Analyst" in prompt else "recommender")
        if role in self.garble_roles and not is_repair:
            self.seen.append((role, prompt, kwargs))
            return GARBLED
        return super().__call__(kwargs)


def budget_warnings(r):
    return [w for w in r["warnings"] if "per-run LLM budget reached" in w]


def test_default_budget_is_12_calls_and_50k_tokens():
    s = get_settings()
    assert s.max_llm_calls_per_run == 12 and s.max_tokens_per_run == 50000


def test_g05_pattern_completes_within_12_calls(container):
    """Analyst repairs in both rounds + one revision = 9 calls: the final judge now runs (it was refused at 8)."""
    router = RepairRouter({"analyst"}, judge_scores=(BAD_SCORES, GOOD_SCORES))
    r = run(container, llm=FakeLLM([router] * 40, llm_cache_enabled=False))
    assert r["meta"]["llm_calls"] == 9 and not budget_warnings(r)
    assert r["status"] == "ok" and r["validation"]["verdict"] == "pass" and r["validation"]["revisions"] == 1


def test_same_pattern_under_the_old_cap_of_8_loses_the_final_judge(container):
    router = RepairRouter({"analyst"}, judge_scores=(BAD_SCORES, GOOD_SCORES))
    r = run(container, llm=FakeLLM([router] * 40, llm_cache_enabled=False, max_llm_calls_per_run=8))
    assert r["meta"]["llm_calls"] == 8 and budget_warnings(r)
    assert r["status"] == "degraded" and r["validation"]["verdict"] == "unvalidated"


def test_call_cap_exhaustion_at_12_degrades_cleanly(container):
    """Every agent call needs a repair in both rounds: 14 calls wanted, 12 allowed -> the last judge is refused."""
    router = RepairRouter({"classifier", "analyst", "recommender", "judge"}, judge_scores=(BAD_SCORES, GOOD_SCORES))
    r = run(container, llm=FakeLLM([router] * 40, llm_cache_enabled=False))
    assert r["meta"]["llm_calls"] == 12
    assert r["status"] == "degraded" and r["validation"]["verdict"] == "unvalidated" and budget_warnings(r)
    assert ("judge", "fallback") in [(t["node"], t["status"]) for t in r["trace"]]
    assert r["recommendations"] and r["root_cause_analysis"]["hypotheses"]  # a complete answer is still returned


def test_token_budget_exhaustion_degrades_cleanly(container):
    """150 tokens per call, 500-token budget: classify, analyst, recommender and judge run (600 tokens); the revision
    round is refused and every remaining node falls back. No exception, still a full response."""
    router = Router(judge_scores=(BAD_SCORES, GOOD_SCORES))
    r = run(container, llm=FakeLLM([router] * 40, llm_cache_enabled=False, max_tokens_per_run=500))
    assert r["meta"]["llm_calls"] == 4 and r["meta"]["tokens_in"] + r["meta"]["tokens_out"] == 600
    assert r["status"] == "degraded" and budget_warnings(r)
    fallbacks = [t["node"] for t in r["trace"] if t["status"] == "fallback"]
    assert fallbacks == ["analyze", "recommend", "judge"] and r["validation"]["verdict"] == "unvalidated"
    assert r["recommendations"] and r["root_cause_analysis"]["hypotheses"]

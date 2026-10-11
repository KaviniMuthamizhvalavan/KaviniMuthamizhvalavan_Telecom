"""Multi-agent troubleshooting workflow (LangGraph StateGraph; plan §2.5, §8.7, §8.8).

START -> gate --(LLM available)--> classify --(reject | clarify)--> finalize
                                     \\-> retrieve -> gather_evidence -> analyze -> recommend -> judge
                                                                          ^           ^          |
                                                         revise(analyst) -+   revise(recommender)+ (once)
             --(no key / circuit open)--> rules -> retrieve -> gather_evidence -> reduced -> finalize
Every LLM node has a deterministic fallback; a fallback marks the run "degraded" and names the step.
"""
import logging
import time
from functools import partial

from langgraph.graph import END, START, StateGraph

from src.agents import analyst_agent, classifier_agent, judge_agent, recommender_agent, tools
from src.agents.state import TroubleshootState
from src.rag.filters import SearchFilters
from src.services.llm_client import LLMBudgetExceeded, LLMError

log = logging.getLogger(__name__)
PROMPT_VERSIONS = {"classifier": classifier_agent.PROMPT_VERSION, "analyst": analyst_agent.PROMPT_VERSION,
                   "recommender": recommender_agent.PROMPT_VERSION, "judge": judge_agent.PROMPT_VERSION}


# ---------------------------------------------------------------------------- helpers
def _traced(name: str, fn, c, state: TroubleshootState) -> dict:
    """Run a node, append {node, ms, llm_calls, tokens_in, tokens_out, tool_calls, status} to the trace."""
    usage = state["usage"]
    before = (usage.llm_calls, usage.tokens_in, usage.tokens_out)
    t0 = time.perf_counter()
    update = fn(c, state) or {}
    entry = {"node": name, "ms": round((time.perf_counter() - t0) * 1000, 1),
             "llm_calls": usage.llm_calls - before[0], "tokens_in": usage.tokens_in - before[1],
             "tokens_out": usage.tokens_out - before[2], "tool_calls": update.pop("_tools", []),
             "status": update.pop("_status", "ok")}
    update["trace"] = [*state.get("trace", []), entry]
    return update


def _degrade(state: TroubleshootState, step: str, exc: Exception | None, message: str) -> dict:
    warn = message if exc is None else f"{message} ({type(exc).__name__})"
    if isinstance(exc, LLMBudgetExceeded):
        warn = f"{message} (per-run LLM budget reached)"
    log.warning("troubleshoot %s fallback: %s", step, exc)
    return {"status": "degraded", "degraded_steps": [*state.get("degraded_steps", []), step],
            "warnings": [*state.get("warnings", []), warn], "_status": "fallback"}


FALLBACK_WARNING_PREFIX = {"analyze": "The analyst agent was unavailable",
                           "recommend": "The recommender agent was unavailable",
                           "judge": "The judge was unavailable"}


def _recovered(state: TroubleshootState, step: str) -> dict:
    """After a revision succeeds where an earlier attempt fell back, the output shown is the LLM's again: drop that
    step's fallback marker and warning so status/warnings describe the final result (the trace keeps the history)."""
    steps = state.get("degraded_steps", [])
    if step not in steps:
        return {}
    remaining = [s for s in steps if s != step]
    prefix = FALLBACK_WARNING_PREFIX[step]
    return {"degraded_steps": remaining,
            "warnings": [w for w in state.get("warnings", []) if not w.startswith(prefix)],
            "status": "degraded" if remaining else "ok"}


def _judge_llm(c):
    return getattr(c, "judge_llm", None) or c.llm


# ---------------------------------------------------------------------------- nodes
def gate(c, s):
    return {"route": "full" if (c.llm is not None and c.llm.available) else "reduced",
            "status": "ok", "revision_count": 0, "revision_instructions": {}, "degraded_steps": []}


def classify(c, s):
    cls, warnings, degraded = classifier_agent.classify(c.llm, s["guardrail"]["text"], s.get("assessment"), s["usage"])
    out = {"classification": cls.model_dump(), "warnings": [*s.get("warnings", []), *warnings]}
    if degraded:
        out.update(_degrade({**s, "warnings": out["warnings"]}, "classify", None,
                            "The LLM classifier was unavailable; a rule-based classification is used."))
    if not cls.in_scope:
        if s["guardrail"]["band"] == "uncertain":
            out["rejected"] = True
        else:
            out["classification"]["in_scope"] = True
            out["warnings"] = [*out["warnings"], "The classifier doubted the query is about network operations; "
                                                 "it was processed because it matched network terms."]
    if cls.needs_clarification and not out.get("rejected"):
        out["status"] = "needs_clarification"
    return out


def rules(c, s):
    cls, _, _ = classifier_agent.classify(None, s["guardrail"]["text"], s.get("assessment"), s["usage"])
    out = {"classification": cls.model_dump(), "status": "degraded", "degraded_steps": ["llm_unavailable"],
           "warnings": [*s.get("warnings", []), "Reduced mode: no LLM is configured or reachable. Classification, "
                                                "analysis and actions are rule-based and not validated."]}
    if cls.needs_clarification:
        out["status"] = "needs_clarification"
    return out


def retrieve(c, s):
    req, cls = s["request"], s["classification"]
    explicit = req.get("filters") or SearchFilters()
    merged = explicit.model_dump()
    for key in ("state", "season", "weather"):
        if not merged.get(key) and cls["filters"].get(key):
            merged[key] = cls["filters"][key]
    if not merged.get("city") and cls["filters"].get("city"):
        merged["city"] = cls["filters"]["city"]
    category = cls["primary_category"]
    kwargs = dict(top_k=req["top_k"], query_symptoms=cls["symptoms"], category=category)
    warnings = list(s.get("warnings", []))
    try:
        res = c.retriever.search(s["guardrail"]["text"], filters=SearchFilters(**merged), **kwargs)
    except Exception as exc:  # e.g. an unknown city extracted by the classifier
        log.warning("retrieve with extracted filters failed: %s", exc)
        res = {"total_candidates": 0, "results": [], "warnings": []}
    tools_used = ["hybrid_search"]
    if res["total_candidates"] == 0 and merged != explicit.model_dump():
        res = c.retriever.search(s["guardrail"]["text"], filters=explicit, use_rule_expansion=False, **kwargs)
        warnings.append("No cases matched the extracted filters; retried with only the filters you set.")
        tools_used.append("hybrid_search_retry")
    res.pop("query_symptoms", None)
    return {"similar_cases": res["results"], "total_candidates": res["total_candidates"],
            "applied_filters": res.get("applied_filters", {}), "warnings": [*warnings, *res["warnings"]],
            "_tools": tools_used}


def gather_evidence(c, s):
    cls, req = s["classification"], s["request"]
    ids = [x["case_id"] for x in s["similar_cases"]]
    assessment, basis, kpis = tools.kpi_basis(c, req.get("kpis"), ids)
    out = {"assessment": assessment, "kpi_basis": basis,
           "segment_stats": tools.segment_stats(c, s.get("applied_filters", {}), cls["symptoms"]),
           "fault_risk": None, "performance": None, "impact": None, "priority": None}
    used = ["kpi_assessment", "segment_stats"]
    if assessment is not None:
        risk, perf = tools.predict(c, kpis)
        impact, priority = tools.impact_and_priority(c, assessment, risk["probability"])
        if basis == "similar_cases_median":
            priority["reasons"].insert(0, "Estimated from the median KPIs of the similar cases (no KPIs were given).")
        out.update(fault_risk={**risk, "basis": basis}, performance=perf, impact=impact, priority=priority)
        used += ["predict_fault_risk", "predict_performance", "impact", "prioritize"]
    cats = [cls["primary_category"], *cls["secondary_categories"]]
    text = s["guardrail"]["text"]
    out["kb_analyst"] = tools.search_runbook(c, text, cats, role="analyst", k=4)
    out["kb_recommender"] = tools.search_runbook(c, text, cats, role="recommender", k=4)
    out["_tools"] = [*used, "search_runbook(analyst)", "search_runbook(recommender)"]
    return out


def analyze(c, s):
    try:
        return {"analysis": analyst_agent.analyze(c.llm, s, s["usage"]), **_recovered(s, "analyze")}
    except LLMError as exc:
        return {"analysis": analyst_agent.fallback(c, s),
                **_degrade(s, "analyze", exc, "The analyst agent was unavailable; a rule-based analysis is shown.")}


def recommend(c, s):
    try:
        out = recommender_agent.recommend(c.llm, s, s["usage"])
        update = _recovered(s, "recommend")
    except LLMError as exc:
        out = recommender_agent.fallback(c, s)
        update = _degrade(s, "recommend", exc, "The recommender agent was unavailable; runbook actions are shown.")
    return {**update, "recommendations": out["recommendations"], "escalation": out["escalation"],
            "removed_rec_citations": out["removed_citations"],
            "sources": _merge_sources(s["analysis"]["sources"], out["sources"])}


def judge(c, s):
    try:
        v = judge_agent.judge(_judge_llm(c), s, s["usage"])
        update = _recovered(s, "judge")
    except LLMError as exc:
        v = judge_agent.rules_only(s)
        update = _degrade(s, "judge", exc, "The judge was unavailable; only rule checks were run.")
    revisions = s.get("revision_count", 0)
    nxt = "finalize"
    if v["verdict"] == "fail" and revisions < s["request"]["max_revisions"]:
        plan = judge_agent.revision_plan(v)
        nxt = "analyze" if plan["analyst"] else "recommend"
        update.update(revision_instructions=plan, revision_count=revisions + 1)
    v["revisions"] = update.get("revision_count", revisions)
    return {**update, "validation": v, "next_after_judge": nxt}


def reduced(c, s):
    analysis = analyst_agent.fallback(c, s)
    s2 = {**s, "analysis": analysis}
    rec = recommender_agent.fallback(c, s2)
    v = judge_agent.rules_only({**s2, "recommendations": rec["recommendations"], "escalation": rec["escalation"],
                                "removed_rec_citations": rec["removed_citations"]})
    v["revisions"] = 0
    return {"analysis": analysis, "recommendations": rec["recommendations"], "escalation": rec["escalation"],
            "sources": _merge_sources(analysis["sources"], rec["sources"]), "validation": v}


def finalize(c, s):
    out = {}
    v = s.get("validation")
    if v and v["verdict"] == "fail":
        out["warnings"] = [*s.get("warnings", []), "Low-confidence diagnosis: the validator found issues it could "
                                                   "not resolve; review the issues before acting."]
    return out


def _merge_sources(*lists: list[dict]) -> list[dict]:
    seen, out = set(), []
    for src in (x for lst in lists for x in lst):
        if src["id"] not in seen:
            seen.add(src["id"])
            out.append(src)
    return out


# ---------------------------------------------------------------------------- routing
def after_gate(s):
    return "classify" if s["route"] == "full" else "rules"


def after_classify(s):
    if s.get("rejected") or s["status"] == "needs_clarification":
        return "finalize"
    return "retrieve"


def after_rules(s):
    return "finalize" if s["status"] == "needs_clarification" else "retrieve"


def after_evidence(s):
    return "analyze" if s["route"] == "full" else "reduced"


def after_judge(s):
    return s["next_after_judge"]


def build_graph(c):
    g = StateGraph(TroubleshootState)
    nodes = {"gate": gate, "classify": classify, "rules": rules, "retrieve": retrieve,
             "gather_evidence": gather_evidence, "analyze": analyze, "recommend": recommend, "judge": judge,
             "reduced": reduced, "finalize": finalize}
    for name, fn in nodes.items():
        g.add_node(name, partial(_traced, name, fn, c))
    g.add_edge(START, "gate")
    g.add_conditional_edges("gate", after_gate, ["classify", "rules"])
    g.add_conditional_edges("classify", after_classify, ["retrieve", "finalize"])
    g.add_conditional_edges("rules", after_rules, ["retrieve", "finalize"])
    g.add_edge("retrieve", "gather_evidence")
    g.add_conditional_edges("gather_evidence", after_evidence, ["analyze", "reduced"])
    g.add_edge("analyze", "recommend")
    g.add_edge("recommend", "judge")
    g.add_conditional_edges("judge", after_judge, ["analyze", "recommend", "finalize"])
    g.add_edge("reduced", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


def export_mermaid(path) -> str:
    """Write the graph diagram (plan Phase 8 task 2). Uses a stub container: only the topology matters."""
    text = build_graph(None).get_graph().draw_mermaid()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text

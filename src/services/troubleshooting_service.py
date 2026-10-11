"""Service facade for Requirement 1: guarded search, classification and basic single-pass RAG (plan Phase 6).

Guardrails run here, before retrieval or any LLM call. LLM failures never raise to the API: they degrade to
deterministic output (rule classification, runbook actions verbatim) with status="degraded".
"""
import logging
import time
import uuid
from pathlib import Path

from pydantic import BaseModel, Field

from src.agents import classifier_agent
from src.agents.tools import runbook_chunk as _runbook_chunk
from src.agents.tools import runbook_items as _bullets
from src.rag import context_builder
from src.rag.filters import SearchFilters
from src.rag.hybrid_retriever import search_kb
from src.services.guardrails import GuardrailError, GuardrailResult
from src.services.kpi_analyzer import assess, profile_from_cases
from src.services.llm_client import LLMError
from src.services.prioritization import prioritize
from src.utils.schema import CATEGORIES, NORMAL

log = logging.getLogger(__name__)
BASIC_PROMPT_VERSION = "basic_rag_v1"
BASIC_PROMPT = Path(__file__).resolve().parents[1] / "agents" / "prompts" / f"{BASIC_PROMPT_VERSION}.md"
BASIC_MAX_TOKENS = 900
UNCERTAIN_WARNING = "The query may not be about network operations; results may not be relevant."


class Cause(BaseModel):
    cause: str
    citations: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    step: int
    action: str
    rationale: str = ""
    citations: list[str] = Field(default_factory=list)


class BasicAnswer(BaseModel):
    summary: str
    likely_causes: list[Cause] = Field(default_factory=list, max_length=6)
    recommendations: list[Recommendation] = Field(min_length=1, max_length=8)


def _check(c, query: str, allow_uncertain: bool) -> GuardrailResult:
    g = c.guardrails.check(query)
    if g.band == "uncertain" and allow_uncertain:
        g.warnings.append(UNCERTAIN_WARNING)
    return g


# ---------------------------------------------------------------------------- search
def search(c, query: str, filters: SearchFilters | None, top_k: int, mode: str, use_rule_expansion: bool) -> dict:
    g = _check(c, query, allow_uncertain=True)  # /search has no classifier to decide the uncertain band
    # Feedback priors are per incident category (plan §8.6, §9.3): /search takes its category from the
    # rule-based classifier (no LLM call). Priors only affect hybrid_rerank, as before.
    category = classifier_agent.rule_classify(g.text).primary_category
    res = c.retriever.search(g.text, filters=filters, top_k=top_k, mode=mode, use_rule_expansion=use_rule_expansion,
                             category=category)
    res.pop("query_symptoms", None)
    res["warnings"] = [*g.warnings, *res["warnings"]]
    return res


# ---------------------------------------------------------------------------- classify
def classify(c, query: str, kpis: dict | None) -> dict:
    g = c.guardrails.check(query)
    usage = c.llm.new_usage()
    assessment = assess(kpis, c.baselines) if kpis else None
    cls, warnings, degraded = classifier_agent.classify(c.llm, g.text, assessment, usage)
    warnings = [*g.warnings, *warnings]
    if g.band == "uncertain":
        if degraded:
            warnings.append(UNCERTAIN_WARNING)
        elif not cls.in_scope:
            raise GuardrailError("OUT_OF_SCOPE", "This assistant answers questions about mobile network operations.",
                                 {"relevance": g.relevance, "decided_by": "classifier"})
    status = "needs_clarification" if cls.needs_clarification else ("degraded" if degraded else "ok")
    return {"status": status, "classification": cls.model_dump(), "kpi_assessment": _assessment_view(assessment),
            "warnings": warnings, "usage": usage.summary()}


def _assessment_view(a: dict | None, basis: str = "provided_kpis") -> dict | None:
    if not a:
        return None
    return {"basis": basis, "anomalies": a["anomalies"], "symptoms": a["symptoms"],
            "primary_category": a["primary_category"], "imputed_fields": a["imputed_fields"]}


# ---------------------------------------------------------------------------- basic RAG
def basic_recommend(c, query: str, filters: SearchFilters | None, kpis: dict | None, top_k: int) -> dict:
    t0 = time.perf_counter()
    g = _check(c, query, allow_uncertain=True)  # 1-call baseline: no classifier, so uncertain is allowed
    run_id = uuid.uuid4().hex
    usage = c.llm.new_usage()
    res = c.retriever.search(g.text, filters=filters, top_k=top_k)
    warnings = [*g.warnings, *res["warnings"]]
    cases = res["results"]

    rules = classifier_agent.rule_classify(g.text)
    if rules.symptoms:
        category = rules.primary_category
    elif cases:
        category = max({x["primary_category"] for x in cases}, key=[x["primary_category"] for x in cases].count)
    else:
        category = NORMAL

    if kpis:
        assessment, basis = assess(kpis, c.baselines), "provided_kpis"
        risk = c.predictor.predict_fault_risk(kpis)["probability"]
    elif cases:
        ids = [x["case_id"] for x in cases]
        profile = profile_from_cases(c.cases.iloc[[c.case_index[i] for i in ids]])
        assessment, basis = assess(profile, c.baselines), "similar_cases_median"
        risk = float(c.cases.iloc[[c.case_index[i] for i in ids]]["fault_risk_prob"].median())
    else:
        assessment = None
    priority = prioritize(assessment, risk, c.baselines) if assessment else None
    if priority and basis == "similar_cases_median":
        priority["reasons"].insert(0, "Estimated from the median KPIs of the similar cases (no KPIs were given).")

    kb = search_kb(c.store, c.embedder, g.text, categories=[category] if category != NORMAL else [NORMAL],
                   role="basic", k=4)
    pack = context_builder.build(
        g.text, similar_cases=cases, runbook=kb,
        kpi_assessment=context_builder.assessment_text(assessment, basis) if assessment else None,
        impact_priority=context_builder.priority_text(priority) if priority else None)

    status, answer = "ok", None
    if c.llm.available:
        prompt = BASIC_PROMPT.read_text(encoding="utf-8").replace("{{evidence}}", pack.text)
        try:
            raw = c.llm.generate_json([{"role": "system", "content": prompt}, {"role": "user", "content": g.text}],
                                      BasicAnswer, max_tokens=BASIC_MAX_TOKENS, usage=usage, purpose="basic_rag",
                                      prompt_version=BASIC_PROMPT_VERSION)
            answer = _enforce_citations(raw, pack.allowed_ids, warnings)
        except LLMError as exc:
            log.warning("basic RAG fallback to runbook actions: %s", exc)
            warnings.append("The LLM was unavailable; runbook actions are shown verbatim.")
    else:
        warnings.append("No LLM is configured or reachable; runbook actions are shown verbatim (reduced mode).")
    if answer is None:
        status, answer = "degraded", runbook_fallback(c, category, cases)
        pack.sources += [s for s in _fallback_sources(c, category) if s["id"] not in pack.allowed_ids]

    log.info("recommend run=%s status=%s category=%s cases=%d llm_calls=%d %.0fms", run_id, status, category,
             len(cases), usage.llm_calls, (time.perf_counter() - t0) * 1000)
    from src.services.feedback_service import save_safely
    save_safely(getattr(c, "runs", None), run_id=run_id, endpoint="recommend", query=g.text,
                request={"filters": filters.model_dump(exclude_none=True) if filters else None, "kpis": kpis,
                         "top_k": top_k},
                response={"answer": answer, "priority": priority, "sources": pack.sources, "warnings": warnings},
                status=status, primary_category=category, priority=(priority or {}).get("level"), judge_verdict=None,
                model=c.llm.model if status == "ok" else "none", prompt_version=BASIC_PROMPT_VERSION,
                latency_ms=round((time.perf_counter() - t0) * 1000, 1), tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out)
    # Response fields follow the /recommend contract (plan §9.3); run persistence arrives with the runs table (Phase 8).
    return {"run_id": run_id, "status": status, "parsed": {"symptoms": res["parsed"]["symptoms"],
                                                           "filters": res["parsed"]["filters"]},
            "similar_cases": cases, "answer": answer, "priority": priority, "sources": pack.sources,
            "warnings": warnings, "usage": usage.summary()}


def _enforce_citations(a: BasicAnswer, allowed: set[str], warnings: list[str]) -> dict:
    """Strip IDs not in the evidence pack (plan §7.10); flag recommendations left without a KB citation."""
    removed_all = []
    for item in [*a.likely_causes, *a.recommendations]:
        item.citations, removed = context_builder.strip_unknown(item.citations, allowed)
        removed_all += removed
    if removed_all:
        warnings.append(f"Removed citations not present in the evidence: {sorted(set(removed_all))}")
    no_kb = [r.step for r in a.recommendations if not any(x.startswith("KB-") for x in r.citations)]
    if no_kb:
        warnings.append(f"Recommendations without a runbook citation: steps {no_kb}")
    return a.model_dump()


# ---------------------------------------------------------------------------- deterministic fallback
def runbook_fallback(c, category: str, cases: list[dict]) -> dict:
    actions = _runbook_chunk(c, category, "corrective-actions") or _runbook_chunk(c, NORMAL, "corrective-actions")
    causes = _runbook_chunk(c, category, "likely-root-causes")
    recs = []
    if actions:
        for i, (phase, item) in enumerate(_bullets(actions["text"])[:6], start=1):
            recs.append({"step": i, "action": item, "rationale": f"Runbook {phase.lower() or 'corrective'} action.",
                         "citations": [actions["kb_id"]]})
    if not recs:
        recs = [{"step": 1, "action": "Triage manually and escalate to the NOC duty engineer; no runbook was found.",
                 "rationale": "No runbook actions are available for this incident type.", "citations": []}]
    likely = [{"cause": item, "citations": [causes["kb_id"]]} for _, item in _bullets(causes["text"])[:4]] \
        if causes else []
    name = CATEGORIES[category].name if category in CATEGORIES else "No clear incident type"
    summary = (f"Reduced mode: no LLM summary. {len(cases)} similar past cases were retrieved; the query was "
               f"matched to '{name}' and the runbook's corrective actions are listed as written.")
    return {"summary": summary, "likely_causes": likely, "recommendations": recs}


def _fallback_sources(c, category: str) -> list[dict]:
    out = []
    for cat, section in ((category, "corrective-actions"), (NORMAL, "corrective-actions"),
                         (category, "likely-root-causes")):
        k = _runbook_chunk(c, cat, section)
        if k:
            out.append({"id": k["kb_id"], "type": "runbook", "title": f"{k['title']} / {k['section']}",
                        "snippet": k["text"][:240], "score": None})
    return out


# ---------------------------------------------------------------------------- multi-agent troubleshoot (Phase 8)
def run_troubleshoot(c, query: str, filters: SearchFilters | None, kpis: dict | None, top_k: int,
                     max_revisions: int, include_trace: bool) -> dict:
    from src.agents import graph as agent_graph

    t0 = time.perf_counter()
    g = c.guardrails.check(query)  # rejected input never reaches an LLM
    usage = c.llm.new_usage()
    if getattr(c, "graph", None) is None:
        c.graph = agent_graph.build_graph(c)
    state = c.graph.invoke({
        "request": {"query": query, "filters": filters, "kpis": kpis, "top_k": top_k, "max_revisions": max_revisions},
        "guardrail": {"text": g.text, "band": g.band, "relevance": g.relevance},
        "assessment": assess(kpis, c.baselines) if kpis else None,
        "warnings": list(g.warnings), "trace": [], "usage": usage})
    if state.get("rejected"):
        raise GuardrailError("OUT_OF_SCOPE", "This assistant answers questions about mobile network operations.",
                             {"relevance": g.relevance, "decided_by": "classifier"})
    warnings = state.get("warnings", [])
    if g.band == "uncertain" and state["route"] == "reduced":
        warnings.append(UNCERTAIN_WARNING)
    latency = round((time.perf_counter() - t0) * 1000, 1)
    resp = troubleshoot_response(c, state, warnings, latency, include_trace)
    from src.services.feedback_service import save_safely
    save_safely(getattr(c, "runs", None), run_id=resp["run_id"], endpoint="troubleshoot", query=g.text,
                request={"filters": filters.model_dump(exclude_none=True) if filters else None, "kpis": kpis,
                         "top_k": top_k, "max_revisions": max_revisions},
                response=resp, status=resp["status"], primary_category=resp["classification"]["primary_category"],
                priority=(resp["priority"] or {}).get("level"), judge_verdict=(resp["validation"] or {}).get("verdict"),
                model=resp["meta"]["model"], prompt_version=resp["meta"]["prompt_version"], latency_ms=latency,
                tokens_in=usage.tokens_in, tokens_out=usage.tokens_out)
    log.info("troubleshoot run=%s status=%s route=%s verdict=%s llm_calls=%d tokens=%d %.0fms", resp["run_id"],
             resp["status"], state["route"], (resp["validation"] or {}).get("verdict"), usage.llm_calls,
             usage.tokens_in + usage.tokens_out, latency)
    return resp


def troubleshoot_response(c, s: dict, warnings: list[str], latency_ms: float, include_trace: bool) -> dict:
    """Shape the final state into the /troubleshoot contract (plan §9.3 #7)."""
    from src.agents.graph import PROMPT_VERSIONS

    usage = s["usage"]
    a, seg, risk, perf, an = (s.get("assessment"), s.get("segment_stats") or {}, s.get("fault_risk"),
                              s.get("performance"), s.get("analysis"))
    judge_llm = getattr(c, "judge_llm", None) or c.llm
    return {
        "run_id": uuid.uuid4().hex, "status": s["status"], "classification": s["classification"],
        "applied_filters": s.get("applied_filters", {}), "similar_cases": s.get("similar_cases", []),
        "kpi_assessment": {"basis": s["kpi_basis"], "anomalies": a["anomalies"], "imputed_fields": a["imputed_fields"]}
        if a and s.get("kpi_basis") else None,
        "segment_stats": {"count": seg.get("count", 0), "top_lifts": seg.get("top_lifts", []),
                          "priority_mix": seg.get("priority_mix", {}), "median_fault_rate": seg.get("median_fault_rate")}
        if seg else None,
        "root_cause_analysis": {"hypotheses": an["hypotheses"], "contributing_factors": an["contributing_factors"],
                                "data_limitations": an["data_limitations"]} if an else None,
        "impact": an["impact"] if an else None,
        "fault_risk": {"probability": risk["probability"], "band": risk["band"], "top_drivers": risk["top_drivers"],
                       "basis": risk["basis"]} if risk else None,
        "performance_prediction": {"expected_throughput_mbps": perf["expected_throughput_mbps"],
                                   "observed": perf["observed_throughput_mbps"], "deficit_pct": perf["deficit_pct"],
                                   "model_r2": perf["model"]["r2"]} if perf else None,
        "priority": s.get("priority"), "recommendations": s.get("recommendations", []),
        "escalation": s.get("escalation"), "validation": s.get("validation"), "sources": s.get("sources", []),
        "warnings": warnings, "trace": s.get("trace", []) if include_trace else [],
        "meta": {"model": c.llm.model if s["route"] == "full" else "none",
                 "judge_model": judge_llm.model if s["route"] == "full" else "none",
                 "prompt_version": ",".join(PROMPT_VERSIONS.values()), "latency_ms": latency_ms,
                 "llm_calls": usage.llm_calls, "tokens_in": usage.tokens_in, "tokens_out": usage.tokens_out,
                 "cached_calls": usage.cached_calls},
        "usage": usage.summary(),
    }

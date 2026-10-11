"""Evidence pack for LLM prompts (plan §7.8, §7.10).

Sections appear in a fixed order, each with a token budget. Over budget, the lowest-ranked items of a list
section are dropped whole, so an ID is never cut. The pack also returns the allowed citation IDs and the
`sources[]` list for the response.
"""
from dataclasses import dataclass, field

DATA_LIMITATIONS = ("Synthetic dataset; no timestamps, cell IDs or topology. Severity is relative to this "
                    "network's history (percentiles), not absolute thresholds. Correlations in past cases are "
                    "not proof of causation.")

BUDGETS = {"QUERY": 150, "CLASSIFICATION": 120, "KPI ASSESSMENT": 250, "SIMILAR CASES": 500, "SEGMENT STATS": 250,
           "PREDICTIONS": 120, "IMPACT & PRIORITY": 150, "RUNBOOK EXCERPTS": 1000, "DATA LIMITATIONS": 80}
ORDER = list(BUDGETS)
# The recommender's pack leads with the analysis and runbook actions, then compact case references (plan §7.8).
ANALYSIS_BUDGET = 500
RECOMMENDER_ORDER = ["QUERY", "CLASSIFICATION", "ANALYSIS", "IMPACT & PRIORITY", "RUNBOOK EXCERPTS", "SIMILAR CASES",
                     "DATA LIMITATIONS"]
# Data-evidence section labels the analyst may cite besides CASE-/KB- IDs (they are not documents).
# IMPACT & PRIORITY added 2026-10-09: it is in the analyst's evidence and the judge's digest, and the analyst prompt
# refers to it by that label; Claude Haiku 5.5 cited it in most test runs, and the rule then removed a valid source.
SECTION_CITATIONS = {"KPI ASSESSMENT", "SEGMENT STATS", "PREDICTIONS", "IMPACT & PRIORITY"}


def tokens(text: str) -> int:
    """Rough token estimate (about 4 characters per token for English)."""
    return max(1, len(text) // 4)


def _fit(items: list[str], budget: int) -> list[str]:
    out, used = [], 0
    for item in items:
        t = tokens(item)
        if used + t > budget and out:
            break
        out.append(item)
        used += t
    return out


def _clip(text: str, budget: int) -> str:
    limit = budget * 4
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " ..."


@dataclass
class EvidencePack:
    text: str
    allowed_ids: set[str]
    sources: list[dict] = field(default_factory=list)
    token_estimate: int = 0


def case_line(c: dict) -> str:
    return (f"[{c['case_id']}] {c['primary_category']} | {c['state']}, {c['season']}, {c['weather']} | "
            f"priority {c['priority']} | {c['summary']}")


def kb_block(k: dict, max_chars: int = 1400) -> str:
    text = k["text"] if len(k["text"]) <= max_chars else k["text"][:max_chars].rsplit("\n", 1)[0] + "\n..."
    return f"[{k['kb_id']}] {k['title']} / {k['section']}\n{text}"


def build(query: str, *, classification: str | None = None, kpi_assessment: str | None = None,
          similar_cases: list[dict] | None = None, segment_stats: str | None = None, predictions: str | None = None,
          impact_priority: str | None = None, runbook: list[dict] | None = None, analysis: str | None = None,
          order: list[str] | None = None) -> EvidencePack:
    """similar_cases: /search result dicts (ranked). runbook: search_kb hits (ranked). Others: prepared text."""
    similar_cases, runbook = similar_cases or [], runbook or []
    case_lines = _fit([case_line(c) for c in similar_cases], BUDGETS["SIMILAR CASES"])
    kb_lines = _fit([kb_block(k) for k in runbook], BUDGETS["RUNBOOK EXCERPTS"])
    used_cases, used_kb = similar_cases[:len(case_lines)], runbook[:len(kb_lines)]
    sections = {
        "QUERY": _clip(query, BUDGETS["QUERY"]),
        "CLASSIFICATION": classification and _clip(classification, BUDGETS["CLASSIFICATION"]),
        "KPI ASSESSMENT": kpi_assessment and _clip(kpi_assessment, BUDGETS["KPI ASSESSMENT"]),
        "SIMILAR CASES": "\n".join(case_lines) or None,
        "SEGMENT STATS": segment_stats and _clip(segment_stats, BUDGETS["SEGMENT STATS"]),
        "PREDICTIONS": predictions and _clip(predictions, BUDGETS["PREDICTIONS"]),
        "IMPACT & PRIORITY": impact_priority and _clip(impact_priority, BUDGETS["IMPACT & PRIORITY"]),
        "RUNBOOK EXCERPTS": "\n\n".join(kb_lines) or None,
        "ANALYSIS": analysis and _clip(analysis, ANALYSIS_BUDGET),
        "DATA LIMITATIONS": DATA_LIMITATIONS,
    }
    text = "\n\n".join(f"[{name}]\n{sections[name]}" for name in (order or ORDER) if sections.get(name))
    sources = ([{"id": c["case_id"], "type": "case", "title": f"{c['primary_category']} case, {c['state']}",
                 "snippet": c["summary"], "score": c.get("final_score")} for c in used_cases]
               + [{"id": k["kb_id"], "type": "runbook", "title": f"{k['title']} / {k['section']}",
                   "snippet": k["text"][:240], "score": k.get("score")} for k in used_kb])
    ids = {s["id"] for s in sources}
    return EvidencePack(text=text, allowed_ids=ids, sources=sources, token_estimate=tokens(text))


# ---------------------------------------------------------------------------- section text formatters
def assessment_text(a: dict, basis: str) -> str:
    anomalies = "; ".join(f"{x['label']} {x['value']:g} {x['unit']} ({x['band']}, worse than "
                          f"{x['worse_than_pct']:.0f}%)" for x in a["anomalies"][:6]) or "no anomalies"
    return f"Basis: {basis}. Top anomalies: {anomalies}."


def priority_text(p: dict) -> str:
    return f"Priority {p['level']} ({p['label']}), score {p['score']}. Reasons: " + "; ".join(p["reasons"][:4])


def impact_text(i: dict) -> str:
    return (f"Impact {i['level']}: affected services {', '.join(i['affected_services']) or 'none'}; "
            f"{i['users_served']:,} users served (percentile {i['users_percentile']:.0%}); {i['data_gb']:g} GB data.")


def segment_text(s: dict) -> str:
    if not s.get("count"):
        return "No historical cases match the filters and symptoms."
    lifts = "; ".join(f"{x['factor']} {x['lift']}x (segment {x['segment_rate']:.0%} vs corpus {x['corpus_rate']:.0%})"
                      for x in s["top_lifts"][:6] if x["lift"])
    mix = ", ".join(f"{k} {v:.0%}" for k, v in s.get("priority_mix", {}).items())
    return (f"{s['count']} matching historical cases ({s['share_of_corpus']:.1%} of corpus), defined by: "
            f"{s.get('definition', 'filters')}. Co-occurrence lifts vs corpus: {lifts}. Priority mix: {mix}. "
            f"Median fault occurrence rate {s['median_fault_rate']}%.")


def predictions_text(risk: dict, perf: dict) -> str:
    drivers = ", ".join(d["feature"] for d in risk["top_drivers"][:4])
    perf_txt = f"expected throughput {perf['expected_throughput_mbps']} Mbps"
    if perf.get("observed_throughput_mbps") is not None:
        perf_txt += (f", observed {perf['observed_throughput_mbps']:g} Mbps (deficit {perf['deficit_pct']}%, "
                     f"{perf['assessment']})")
    return (f"Fault risk {risk['probability']:.2f} ({risk['band']}; model ROC-AUC {risk['model']['roc_auc']}); "
            f"top drivers: {drivers}. Performance model (R2 {perf['model']['r2']}): {perf_txt}.")


def strip_unknown(citations: list[str], allowed: set[str]) -> tuple[list[str], list[str]]:
    """Keep only allowed IDs (brackets tolerated); return (kept, removed)."""
    kept, removed = [], []
    for c in citations:
        cid = str(c).strip().strip("[]")
        (kept if cid in allowed else removed).append(cid)
    return list(dict.fromkeys(kept)), removed

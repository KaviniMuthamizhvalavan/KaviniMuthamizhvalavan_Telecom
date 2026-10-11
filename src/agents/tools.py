"""Deterministic tools used by the multi-agent workflow (plan §8.3 tool table).

The gather_evidence node calls these directly (pre-fetched evidence). The analyst's optional LLM-chosen tool
round is deferred (plan §5.0), so no OpenAI tool schemas are exposed yet.
"""
import re

import numpy as np

from src.rag.filters import SearchFilters, to_mask, validate
from src.rag.hybrid_retriever import search_kb
from src.services.analytics import segment_stats as _segment_stats
from src.services.impact import estimate_impact
from src.services.kpi_analyzer import assess, profile_from_cases
from src.services.prioritization import prioritize
from src.utils.schema import NORMAL


def get_case_details(c, case_id: str) -> dict:
    row = c.cases.iloc[c.case_index[case_id]]
    return {"case_id": case_id, **assess(row.to_dict(), c.baselines)}


def compare_kpis_to_baseline(c, kpis: dict) -> dict:
    return assess(kpis, c.baselines)


def kpi_basis(c, kpis: dict | None, similar_ids: list[str]) -> tuple[dict | None, str, dict | None]:
    """(assessment, basis, kpi dict used for predictions). Basis is the given snapshot, or the median
    profile of the similar cases (an estimate, labelled as such)."""
    if kpis:
        return assess(kpis, c.baselines), "provided_kpis", kpis
    if similar_ids:
        rows = c.cases.iloc[[c.case_index[i] for i in similar_ids]]
        profile = profile_from_cases(rows)
        profile.update(season=rows["season"].mode().iat[0], weather=rows["weather"].mode().iat[0])
        return assess(profile, c.baselines), "similar_cases_median", profile
    return None, "none", None


def segment_stats(c, applied_filters: dict, symptoms: list[str], compare_by: str | None = "season") -> dict:
    """Stats for cases matching the filters and (up to 2 of) the query symptoms; falls back to filters only."""
    base = {k: v for k, v in applied_filters.items() if v}
    for syms, label in ((symptoms[:2], "filters + symptoms"), ([], "filters only")):
        f, _ = validate(SearchFilters(**base, symptoms=syms or None))
        mask = to_mask(f, c.cases)
        if mask.sum() >= 30 or not syms:
            stats = _segment_stats(c.cases, mask, compare_by=compare_by, exclude_symptoms=tuple(syms))
            definition = ", ".join([f"{k}={v}" for k, v in base.items()] + [f"symptoms={s}" for s in syms]) or "all"
            return {**stats, "definition": definition, "segment_basis": label}
    return {"count": 0}


def predict(c, kpis: dict) -> tuple[dict, dict]:
    return c.predictor.predict_fault_risk(kpis), c.predictor.predict_performance(kpis)


def impact_and_priority(c, assessment: dict, risk_prob: float) -> tuple[dict, dict]:
    return estimate_impact(assessment, c.baselines), prioritize(assessment, risk_prob, c.baselines)


def search_runbook(c, text: str, categories: list[str], role: str, k: int = 4) -> list[dict]:
    cats = [x for x in categories if x and x != NORMAL] or [NORMAL]
    return search_kb(c.store, c.embedder, text, categories=cats, role=role, k=k)


def case_risk_median(c, similar_ids: list[str]) -> float:
    return float(np.median(c.cases.iloc[[c.case_index[i] for i in similar_ids]]["fault_risk_prob"]))


# ---------------------------------------------------------------------------- runbook sections
def runbook_chunk(c, category: str, section: str) -> dict | None:
    from src.rag.vector_store import KB
    got = c.store.collection(KB).get(where={"$and": [{"category": category}, {"section": section}]},
                                     include=["documents", "metadatas"])
    if not got["ids"]:
        return None
    return {"kb_id": got["ids"][0], "text": got["documents"][0], **got["metadatas"][0]}


def runbook_items(text: str) -> list[tuple[str, str]]:
    """(phase, item) pairs from a runbook section ('### Immediate' subheadings, '-' or '1.' items)."""
    out, phase = [], ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("###"):
            phase = line.lstrip("#").strip()
        elif re.match(r"^(-|\d+\.)\s+", line):
            out.append((phase, re.sub(r"^(-|\d+\.)\s+", "", line)))
    return out

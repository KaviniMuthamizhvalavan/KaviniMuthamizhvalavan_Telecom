"""Root-Cause & Impact Analyst Agent (plan §8.3, Requirement 2). Reasoning ON (approved option B).

Input: the analyst evidence pack. Output: ranked hypotheses with evidence type and citations, contributing
factors, an impact narrative (the impact level itself is deterministic) and data limitations.
Fallback: top anomalies, top-lift factors and the runbook's likely root causes, marked degraded.
"""
import copy
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, PrivateAttr, model_validator

from src.agents.tools import runbook_chunk, runbook_items
from src.rag import context_builder
from src.services.llm_client import LLMClient, RunUsage
from src.utils.config import get_settings
from src.utils.schema import NORMAL

log = logging.getLogger(__name__)

PROMPT_VERSION = "analyst_v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md"
MAX_TOKENS = 900
TREND_WORDS = ("increasing", "increase", "rising", "declining", "decline", "decreasing", "trend", "growing", "worsening")
BASE_LIMITATIONS = ["Synthetic dataset without timestamps, cell IDs or topology.",
                    "Severity is relative to this network's history, not absolute thresholds.",
                    "Co-occurrence in past cases does not prove causation."]


class Hypothesis(BaseModel):
    cause: str
    likelihood: Literal["high", "medium", "low"]
    evidence_type: Literal["data", "knowledge", "both"]
    supporting_evidence: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class ContributingFactor(BaseModel):
    factor: str
    direction: str
    evidence: str
    citation: str = ""


MAX_HYPOTHESES, MAX_FACTORS = 3, 6


def normalize_analyst_payload(data) -> tuple[object, list[str]]:
    """P3 (2026-10-09): repair the reply shapes observed in Phase 11 without inventing content.

    - a citation list where a string is expected -> its first item
    - a bare string where a list is expected -> a one-item list
    - non-object items inside `hypotheses` / `contributing_factors` (the "garbled" pattern) -> dropped
    - over-long lists -> the first items kept (the prompt orders hypotheses most likely first)
    Everything else is left to validation: missing required fields, wrong enum values, empty causes, duplicate
    causes or an empty hypothesis list still reject the reply, so the repair call and fallback still apply.
    Returns (normalized copy, human-readable notes); the input is never modified.
    """
    if not isinstance(data, dict):
        return data, []
    d, notes = copy.deepcopy(data), []

    def clean_list(key: str, limit: int):
        items = d.get(key)
        if not isinstance(items, list):
            return
        objects = [x for x in items if isinstance(x, dict)]
        if len(objects) < len(items):
            notes.append(f"{key}: dropped {len(items) - len(objects)} non-object item(s)")
        if len(objects) > limit:
            notes.append(f"{key}: kept the first {limit} of {len(objects)}")
            objects = objects[:limit]
        d[key] = objects

    clean_list("hypotheses", MAX_HYPOTHESES)
    clean_list("contributing_factors", MAX_FACTORS)
    for i, h in enumerate(d.get("hypotheses") or []):
        for key in ("supporting_evidence", "citations"):
            if isinstance(h.get(key), str):
                h[key] = [h[key]]
                notes.append(f"hypotheses[{i}].{key}: string -> one-item list")
    for i, f in enumerate(d.get("contributing_factors") or []):
        cit = f.get("citation")
        if isinstance(cit, list):
            first = next((str(x) for x in cit if isinstance(x, str) and x.strip()), "")
            f["citation"] = first
            notes.append(f"contributing_factors[{i}].citation: list of {len(cit)} -> first item")
        elif cit is None and "citation" in f:
            f["citation"] = ""
            notes.append(f"contributing_factors[{i}].citation: null -> empty")
    if isinstance(d.get("data_limitations"), str):
        d["data_limitations"] = [d["data_limitations"]]
        notes.append("data_limitations: string -> one-item list")
    return d, notes


class AnalystOutput(BaseModel):
    # Field definitions are unchanged: their JSON schema is part of the prompt (schema_hint) and of the cache key.
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=3)
    contributing_factors: list[ContributingFactor] = Field(default_factory=list, max_length=6)
    impact_narrative: str
    data_limitations: list[str] = Field(default_factory=list)
    _normalizations: list[str] = PrivateAttr(default_factory=list)
    _raw: object = PrivateAttr(default=None)

    @model_validator(mode="wrap")
    @classmethod
    def _normalize(cls, data, handler):
        fixed, notes = normalize_analyst_payload(data)
        out = handler(fixed)
        out._normalizations, out._raw = notes, (data if notes else None)
        return out

    @model_validator(mode="after")
    def _semantic_checks(self):
        causes = [h.cause.strip().lower() for h in self.hypotheses]
        if any(not c for c in causes):
            raise ValueError("every hypothesis needs a non-empty cause")
        if len(set(causes)) < len(causes):
            raise ValueError("hypotheses repeat the same cause")
        if not self.impact_narrative.strip():
            raise ValueError("impact_narrative must not be empty")
        return self


def normalization_log_path() -> Path:
    return get_settings().artifacts_dir / "llm_normalizations.jsonl"


def _audit_normalization(notes: list[str], raw) -> None:
    """Every normalization is logged and appended (with the raw, pre-normalization reply) to an audit file."""
    log.warning("analyst output normalized: %s", "; ".join(notes))
    try:
        path = normalization_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "agent": "analyst",
                                 "prompt_version": PROMPT_VERSION, "normalizations": notes, "raw": raw},
                                default=str) + "\n")
    except OSError as exc:  # auditing must never break a run
        log.warning("normalization audit not written: %s", exc)


def build_pack(s: dict) -> context_builder.EvidencePack:
    cls = s["classification"]
    cls_text = (f"Primary: {cls['primary_category']}; secondary: {', '.join(cls['secondary_categories']) or 'none'}; "
                f"symptoms: {', '.join(cls['symptoms']) or 'none'}; severity hint: {cls['severity_hint']}; "
                f"confidence {cls['confidence']} (source {cls['source']}).")
    a = s.get("assessment")
    return context_builder.build(
        s["guardrail"]["text"], classification=cls_text,
        kpi_assessment=context_builder.assessment_text(a, s["kpi_basis"]) + (
            " These values are an estimate from the similar cases." if s["kpi_basis"] == "similar_cases_median" else "")
        if a else None,
        similar_cases=s["similar_cases"], segment_stats=context_builder.segment_text(s["segment_stats"]),
        predictions=context_builder.predictions_text(s["fault_risk"], s["performance"]) if s.get("fault_risk") else None,
        impact_priority=(context_builder.impact_text(s["impact"]) + " " + context_builder.priority_text(s["priority"]))
        if s.get("impact") else None,
        runbook=s["kb_analyst"])


def _revision_text(instructions: list[str]) -> str:
    if not instructions:
        return ""
    return ("\n## Reviewer feedback on your previous answer (fix all of these)\n"
            + "\n".join(f"- {i}" for i in instructions) + "\n")


def analyze(llm: LLMClient, s: dict, usage: RunUsage) -> dict:
    pack = build_pack(s)
    prompt = (PROMPT_PATH.read_text(encoding="utf-8").replace("{{evidence}}", pack.text)
              .replace("{{revision}}", _revision_text(s.get("revision_instructions", {}).get("analyst", []))))
    out = llm.generate_json([{"role": "system", "content": prompt}, {"role": "user", "content": s["guardrail"]["text"]}],
                            AnalystOutput, max_tokens=MAX_TOKENS, usage=usage, purpose="analyst",
                            prompt_version=PROMPT_VERSION, reasoning=llm.s.analyst_reasoning,
                            reasoning_allowance=llm.s.agent_reasoning_allowance)
    if out._normalizations:
        _audit_normalization(out._normalizations, out._raw)
    return {**finish(out.model_dump(), s, pack), "normalizations": list(out._normalizations)}


def finish(raw: dict, s: dict, pack: context_builder.EvidencePack) -> dict:
    """Strip citations outside the evidence; attach the deterministic impact; add trend limitation."""
    allowed = pack.allowed_ids | context_builder.SECTION_CITATIONS
    removed = []
    for h in raw["hypotheses"]:
        h["citations"], r = context_builder.strip_unknown(h["citations"], allowed)
        removed += r
    for f in raw["contributing_factors"]:
        kept, r = context_builder.strip_unknown([f["citation"]] if f["citation"] else [], allowed)
        f["citation"], removed = (kept[0] if kept else ""), removed + r
    limitations = list(dict.fromkeys(raw["data_limitations"] or BASE_LIMITATIONS))
    if any(w in s["guardrail"]["text"].lower() for w in TREND_WORDS) and not any(
            "trend" in x.lower() or "time series" in x.lower() or "timestamp" in x.lower() for x in limitations):
        limitations.append("The data has no time series, so increasing or declining trends cannot be verified.")
    imp = s.get("impact") or {}
    return {"hypotheses": raw["hypotheses"], "contributing_factors": raw["contributing_factors"],
            "data_limitations": limitations, "removed_citations": removed,
            "impact": {"level": imp.get("level"), "affected_services": imp.get("affected_services", []),
                       "users_served": imp.get("users_served"), "data_gb": imp.get("data_gb"),
                       "narrative": raw["impact_narrative"]},
            "allowed_ids": sorted(allowed), "sources": pack.sources}


def fallback(c, s: dict) -> dict:
    """Deterministic analysis: anomalies, top lifts and runbook root causes (plan §8.3 fallback)."""
    pack = build_pack(s)
    category = s["classification"]["primary_category"]
    a = s.get("assessment") or {"anomalies": []}
    data_ev = [f"{x['label']} {x['value']:g} {x['unit']} ({x['band']})" for x in a["anomalies"][:3]]
    causes = runbook_chunk(c, category if category != NORMAL else NORMAL, "likely-root-causes")
    hyps = []
    if causes:
        for _, item in runbook_items(causes["text"])[:3]:
            hyps.append({"cause": item, "likelihood": "medium", "evidence_type": "both" if data_ev else "knowledge",
                         "supporting_evidence": data_ev, "citations": [causes["kb_id"]] + (
                             ["KPI ASSESSMENT"] if data_ev else [])})
        pack.sources.append({"id": causes["kb_id"], "type": "runbook",
                             "title": f"{causes['title']} / {causes['section']}", "snippet": causes["text"][:240],
                             "score": None})
        pack.allowed_ids.add(causes["kb_id"])
    if not hyps:
        hyps = [{"cause": "Insufficient evidence for a specific root cause.", "likelihood": "low",
                 "evidence_type": "data", "supporting_evidence": data_ev, "citations": ["KPI ASSESSMENT"]}]
    factors = [{"factor": x["factor"], "direction": "co-occurs more often than baseline",
                "evidence": f"lift {x['lift']}x (segment {x['segment_rate']:.0%} vs corpus {x['corpus_rate']:.0%})",
                "citation": "SEGMENT STATS"}
               for x in s["segment_stats"].get("top_lifts", [])[:4] if x["lift"] and x["lift"] >= 1.2]
    imp = s.get("impact") or {}
    narrative = (f"Impact {imp.get('level', 'unknown')}: affects {', '.join(imp.get('affected_services', [])) or 'no service-affecting KPI'}"
                 f", about {imp.get('users_served', 0):,} users served." if imp else "Impact could not be estimated.")
    raw = {"hypotheses": hyps, "contributing_factors": factors, "impact_narrative": narrative,
           "data_limitations": list(BASE_LIMITATIONS)}
    return finish(raw, s, pack)

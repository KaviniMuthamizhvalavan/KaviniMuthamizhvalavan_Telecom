"""Troubleshooting Recommender Agent (plan §8.4, Requirements 1 and 2). Reasoning OFF (approved option B).

Input: classification, analysis, priority, impact, runbook action chunks, compact case references.
Output: 4-7 ordered, runbook-cited recommendations and an escalation decision.
Fallback: runbook corrective actions verbatim for the primary and secondary categories, marked degraded.
"""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.agents.tools import runbook_chunk, runbook_items
from src.rag import context_builder
from src.services.llm_client import LLMClient, RunUsage
from src.utils.schema import NORMAL

PROMPT_VERSION = "recommender_v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md"
# Plan §7.9 budgets 900 output tokens; the §8.4 schema (8 fields x up to 7 steps) needs more, so 1400 on NVIDIA.
# Claude (2026-10-09 diagnosis, G05): the 1400 cap was filled by JSON text alone (no thinking; between_tools), the
# complete reply was 1,479 tokens for 6 steps (~230 tokens/step); 8 steps (schema max) ~2,100. 2500 leaves headroom.
MAX_TOKENS = 2500
PHASES = {"immediate": "immediate", "short-term": "short_term", "preventive": "preventive"}
APPROVAL_WORDS = ("requires change approval", "reroute", "restart", "rollback", "roll back", "parameter",
                  "configuration", "capacity", "replace", "realign")


class Recommendation(BaseModel):
    step: int
    action: str
    phase: Literal["immediate", "short_term", "preventive"]
    rationale: str
    expected_kpi_effect: str = ""
    verification: str = ""
    risk_level: Literal["low", "medium", "high"] = "low"
    requires_change_approval: bool = False
    citations: list[str] = Field(default_factory=list)


class Escalation(BaseModel):
    needed: bool
    team: str = ""
    reason: str = ""


class RecommenderOutput(BaseModel):
    recommendations: list[Recommendation] = Field(min_length=1, max_length=8)
    escalation: Escalation


def analysis_text(analysis: dict) -> str:
    hyps = "; ".join(f"({h['likelihood']}, {h['evidence_type']}) {h['cause']} [{', '.join(h['citations'])}]"
                     for h in analysis["hypotheses"])
    factors = "; ".join(f"{f['factor']}: {f['direction']}" for f in analysis["contributing_factors"][:4])
    return f"Hypotheses: {hyps}. Contributing factors: {factors or 'none'}."


def build_pack(s: dict) -> context_builder.EvidencePack:
    cls = s["classification"]
    return context_builder.build(
        s["guardrail"]["text"],
        classification=f"Primary: {cls['primary_category']}; secondary: {', '.join(cls['secondary_categories']) or 'none'}; "
                       f"symptoms: {', '.join(cls['symptoms']) or 'none'}.",
        analysis=analysis_text(s["analysis"]),
        impact_priority=(context_builder.impact_text(s["impact"]) + " " + context_builder.priority_text(s["priority"]))
        if s.get("impact") else None,
        runbook=s["kb_recommender"], similar_cases=s["similar_cases"][:3],
        order=context_builder.RECOMMENDER_ORDER)


def recommend(llm: LLMClient, s: dict, usage: RunUsage) -> dict:
    pack = build_pack(s)
    instructions = s.get("revision_instructions", {}).get("recommender", [])
    revision = ("\n## Reviewer feedback on your previous answer (fix all of these)\n"
                + "\n".join(f"- {i}" for i in instructions) + "\n") if instructions else ""
    prompt = (PROMPT_PATH.read_text(encoding="utf-8").replace("{{evidence}}", pack.text)
              .replace("{{revision}}", revision))
    out = llm.generate_json([{"role": "system", "content": prompt}, {"role": "user", "content": s["guardrail"]["text"]}],
                            RecommenderOutput, max_tokens=MAX_TOKENS, usage=usage, purpose="recommender",
                            prompt_version=PROMPT_VERSION, reasoning=llm.s.recommender_reasoning)
    return finish(out.model_dump(), pack)


def finish(raw: dict, pack: context_builder.EvidencePack) -> dict:
    removed = []
    for i, r in enumerate(raw["recommendations"], start=1):
        r["step"] = i
        r["citations"], rem = context_builder.strip_unknown(r["citations"], pack.allowed_ids)
        removed += rem
    return {**raw, "removed_citations": removed, "allowed_ids": sorted(pack.allowed_ids), "sources": pack.sources}


def fallback(c, s: dict) -> dict:
    """Runbook corrective actions verbatim for the primary and secondary categories (plan §8.4 fallback)."""
    pack = build_pack(s)
    cls = s["classification"]
    cats = [x for x in [cls["primary_category"], *cls["secondary_categories"]] if x] or [NORMAL]
    recs = []
    for cat in cats[:2]:
        chunk = runbook_chunk(c, cat, "corrective-actions")
        if not chunk:
            continue
        pack.sources.append({"id": chunk["kb_id"], "type": "runbook", "title": f"{chunk['title']} / {chunk['section']}",
                             "snippet": chunk["text"][:240], "score": None})
        for phase, item in runbook_items(chunk["text"])[: 5 if cat == cats[0] else 2]:
            recs.append({"step": 0, "action": item, "phase": PHASES.get(phase.lower(), "short_term"),
                         "rationale": f"Runbook {phase.lower() or 'corrective'} action for {cat}.",
                         "expected_kpi_effect": "", "verification": "", "risk_level": "medium" if any(
                             w in item.lower() for w in APPROVAL_WORDS) else "low",
                         "requires_change_approval": any(w in item.lower() for w in APPROVAL_WORDS),
                         "citations": [chunk["kb_id"]]})
    order = {"immediate": 0, "short_term": 1, "preventive": 2}
    recs.sort(key=lambda r: order[r["phase"]])
    if not recs:
        recs = [{"step": 0, "action": "Triage manually and escalate to the NOC duty engineer; no runbook was found.",
                 "phase": "immediate", "rationale": "No runbook actions are available.", "expected_kpi_effect": "",
                 "verification": "", "risk_level": "low", "requires_change_approval": False, "citations": []}]
    level = (s.get("priority") or {}).get("level", "P4")
    esc = runbook_chunk(c, cats[0], "escalation-criteria")
    reason = runbook_items(esc["text"])[0][1] if esc and runbook_items(esc["text"]) else ""
    escalation = {"needed": level in ("P1", "P2"), "team": "NOC duty engineer" if level in ("P1", "P2") else "",
                  "reason": (f"Priority {level}. " + reason).strip()}
    pack.allowed_ids |= {x["id"] for x in pack.sources}
    return finish({"recommendations": recs, "escalation": escalation}, pack)

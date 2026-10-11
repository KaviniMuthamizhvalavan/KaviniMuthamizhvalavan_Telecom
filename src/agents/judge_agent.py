"""Validator Agent: deterministic rule checks + LLM rubric; the verdict is computed in code (plan §8.5).
Reasoning ON (approved option B). Fallback: rule checks only, verdict "unvalidated".
"""
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.rag import context_builder
from src.services.llm_client import LLMClient, RunUsage
from src.utils.schema import NORMAL

PROMPT_VERSION = "judge_v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md"
MAX_TOKENS = 500
PASS_GROUNDEDNESS, PASS_OTHER = 0.70, 0.60
NUMBER_RE = re.compile(r"(?<![\w.-])(\d+(?:\.\d+)?)\s*(%|ms|mbps|gb|dbm|x)\b", re.I)


class Scores(BaseModel):
    groundedness: float = Field(ge=0, le=1)
    kpi_consistency: float = Field(ge=0, le=1)
    actionability: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)


class Issue(BaseModel):
    target: Literal["analyst", "recommender"]
    problem: str
    fix_instruction: str


class JudgeOutput(BaseModel):
    scores: Scores
    issues: list[Issue] = Field(default_factory=list, max_length=5)
    summary: str = ""


# ---------------------------------------------------------------------------- layer 1: rule checks
def _numbers(text: str) -> list[float]:
    return [float(m.group(1)) for m in NUMBER_RE.finditer(text)]


def rule_checks(s: dict, evidence_text: str) -> list[dict]:
    """Each check: {rule, passed, critical, target, detail}."""
    a, recs = s["analysis"], s["recommendations"]
    removed = a.get("removed_citations", []) + s.get("removed_rec_citations", [])
    checks = [{"rule": "citations_valid", "passed": not removed, "critical": False, "target": "analyst",
               "detail": f"removed unknown citations: {sorted(set(removed))}" if removed else "all citations known"}]
    no_kb = [r["step"] for r in recs if not any(c.startswith("KB-") for c in r["citations"])]
    checks.append({"rule": "recommendation_kb_citation", "passed": not no_kb, "critical": True, "target": "recommender",
                   "detail": f"steps without a KB- citation: {no_kb}" if no_kb else "every step cites a runbook"})
    uncited = [i + 1 for i, h in enumerate(a["hypotheses"]) if not h["citations"]]
    checks.append({"rule": "hypotheses_grounded", "passed": not uncited, "critical": False, "target": "analyst",
                   "detail": f"hypotheses without evidence citations: {uncited}" if uncited else
                   "every hypothesis cites evidence"})
    evidence_nums = _numbers(evidence_text)
    claimed = _numbers(" ".join(x for h in a["hypotheses"] for x in [h["cause"], *h["supporting_evidence"]])
                       + " " + " ".join(f["evidence"] for f in a["contributing_factors"]))
    unmatched = sorted({n for n in claimed if not any(abs(n - e) <= max(abs(e) * 0.01, 0.005) for e in evidence_nums)})
    checks.append({"rule": "numbers_match_evidence", "passed": not unmatched, "critical": False, "target": "analyst",
                   "detail": f"numbers not found in the evidence (±1%): {unmatched[:8]}" if unmatched else
                   "all quoted numbers match the evidence"})
    primary = s["classification"]["primary_category"]
    cited = {c for r in recs for c in r["citations"]} | {c for h in a["hypotheses"] for c in h["citations"]}
    addressed = primary == NORMAL or any(c.startswith(f"KB-{primary}-") for c in cited)
    checks.append({"rule": "primary_category_addressed", "passed": addressed, "critical": True,
                   "target": "recommender", "detail": f"{primary} runbook cited" if addressed else
                   f"no {primary} runbook is cited"})
    n = len(recs)
    checks.append({"rule": "recommendation_count", "passed": 4 <= n <= 7, "critical": False, "target": "recommender",
                   "detail": f"{n} recommendations (expected 4-7)"})
    return checks


def verdict(scores: dict | None, checks: list[dict]) -> str:
    critical_fail = any(not c["passed"] and c["critical"] for c in checks)
    if scores is None:
        return "unvalidated"
    ok = (scores["groundedness"] >= PASS_GROUNDEDNESS
          and all(v >= PASS_OTHER for k, v in scores.items() if k != "groundedness"))
    return "pass" if ok and not critical_fail else "fail"


# ---------------------------------------------------------------------------- layer 2: LLM rubric
def evidence_digest(s: dict) -> str:
    pack = context_builder.build(
        s["guardrail"]["text"],
        classification=f"Primary {s['classification']['primary_category']}; symptoms {s['classification']['symptoms']}",
        kpi_assessment=context_builder.assessment_text(s["assessment"], s["kpi_basis"]) if s.get("assessment") else None,
        segment_stats=context_builder.segment_text(s["segment_stats"]),
        predictions=context_builder.predictions_text(s["fault_risk"], s["performance"]) if s.get("fault_risk") else None,
        impact_priority=(context_builder.impact_text(s["impact"]) + " " + context_builder.priority_text(s["priority"]))
        if s.get("impact") else None,
        similar_cases=s["similar_cases"], runbook=s["kb_analyst"] + s["kb_recommender"])
    return pack.text


def judge(llm: LLMClient, s: dict, usage: RunUsage) -> dict:
    digest = evidence_digest(s)
    checks = rule_checks(s, digest)
    rules_txt = "\n".join(f"- {c['rule']}: {'PASS' if c['passed'] else 'FAIL'} ({c['detail']})" for c in checks)
    analysis = {k: s["analysis"][k] for k in ("hypotheses", "contributing_factors", "impact", "data_limitations")}
    prompt = (PROMPT_PATH.read_text(encoding="utf-8").replace("{{rules}}", rules_txt).replace("{{evidence}}", digest)
              .replace("{{analysis}}", json.dumps(analysis, indent=1))
              .replace("{{recommendations}}", json.dumps({"recommendations": s["recommendations"],
                                                          "escalation": s["escalation"]}, indent=1)))
    out = llm.generate_json([{"role": "system", "content": prompt},
                             {"role": "user", "content": "Review the diagnosis and return the JSON verdict."}],
                            JudgeOutput, max_tokens=MAX_TOKENS, usage=usage, purpose="judge",
                            prompt_version=PROMPT_VERSION, reasoning=llm.s.judge_reasoning,
                            reasoning_allowance=llm.s.agent_reasoning_allowance)
    scores = out.scores.model_dump()
    return {"verdict": verdict(scores, checks), "scores": scores, "issues": [i.model_dump() for i in out.issues],
            "summary": out.summary, "rule_checks": checks}


def rules_only(s: dict) -> dict:
    checks = rule_checks(s, evidence_digest(s))
    return {"verdict": "unvalidated", "scores": {}, "issues": [], "summary": "LLM judge unavailable; rule checks only.",
            "rule_checks": checks}


def revision_plan(v: dict) -> dict:
    """Route fixes to the agents named in the issues plus failed rule checks (plan §8.5 revision routing)."""
    plan = {"analyst": [], "recommender": []}
    for i in v["issues"]:
        plan[i["target"]].append(i["fix_instruction"] or i["problem"])
    for c in v["rule_checks"]:
        if not c["passed"]:
            plan[c["target"]].append(f"Rule check failed ({c['rule']}): {c['detail']}.")
    return plan

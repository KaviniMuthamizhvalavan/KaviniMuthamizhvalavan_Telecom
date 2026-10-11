"""Phase 11 generation stage: run systems A and C on rag_golden, capturing everything the evaluation needs.

Run from the repo root:  python -m evaluation.run_e2e_generate [--ids G01,G05] [--cache]
- A = basic RAG (`/recommend` service, 1 LLM call)
- C = multi-agent `/troubleshoot` (classifier, analyst, recommender, judge, one revision)
- B = C's first pass before any judge revision. Captured from inside the C run: it is exactly what
  `max_revisions=0` would return, so no extra LLM calls are needed.
For every system the exact evidence the generator saw is recorded as `retrieval_context` (plan §11.5).
LLM cache OFF by default, so latency, tokens, repairs and fallbacks are real. Uses the runtime LLM API.
Output: evaluation/results/final/deepeval/generations.json
"""
import argparse
import json
import time

from src.agents import judge_agent
from src.rag import context_builder
from src.services import troubleshooting_service as service
from src.services.container import ServiceContainer
from src.utils.config import PROJECT_ROOT, get_settings
from src.utils.net import use_system_certificates

RAG_GOLDEN = PROJECT_ROOT / "tests" / "test_cases" / "rag_golden.json"
OUT = PROJECT_ROOT / "evaluation" / "results" / "final" / "deepeval"
JUDGE_STATE_KEYS = ("guardrail", "classification", "assessment", "kpi_basis", "segment_stats", "fault_risk",
                    "performance", "impact", "priority", "similar_cases", "kb_analyst", "kb_recommender",
                    "analysis", "recommendations", "escalation", "removed_rec_citations")
TEXT_SECTIONS = ("classification", "kpi_assessment", "segment_stats", "predictions", "impact_priority")


# ---------------------------------------------------------------------------- capture hooks
class Capture:
    def __init__(self):
        self.packs, self.judge_passes, self.final_state = [], [], None

    def reset(self):
        self.__init__()


CAP = Capture()
_build, _judge, _resp = context_builder.build, judge_agent.judge, service.troubleshoot_response


def _build_hook(query, **kw):
    CAP.packs.append(kw)
    return _build(query, **kw)


def _judge_hook(llm, s, usage):
    v = _judge(llm, s, usage)
    CAP.judge_passes.append({"analysis": s["analysis"], "recommendations": s["recommendations"],
                             "escalation": s["escalation"], "verdict": v["verdict"], "scores": v["scores"],
                             "issues": v["issues"]})
    return v


def _resp_hook(c, s, *a, **kw):
    CAP.final_state = s
    return _resp(c, s, *a, **kw)


context_builder.build, judge_agent.judge, service.troubleshoot_response = _build_hook, _judge_hook, _resp_hook


# ---------------------------------------------------------------------------- rendering
def evidence_items(packs: list[dict]) -> list[str]:
    """The exact evidence items the generator saw (case lines, full runbook chunks, data sections).
    Model-written text (the analysis passed to the recommender) is not retrieval context and is excluded."""
    items = []
    for kw in packs:
        items += [context_builder.case_line(c) for c in kw.get("similar_cases") or []]
        items += [context_builder.kb_block(k) for k in kw.get("runbook") or []]
        items += [f"[{name.upper().replace('_', ' ')}] {kw[name]}" for name in TEXT_SECTIONS if kw.get(name)]
    return list(dict.fromkeys(items))


def render_c(analysis: dict | None, recs: list[dict], escalation: dict | None) -> str:
    out = []
    if analysis:
        out.append("Likely causes:")
        for i, h in enumerate(analysis["hypotheses"], 1):
            out.append(f"{i}. {h['cause']} (likelihood {h['likelihood']}, evidence: {h['evidence_type']}). "
                       f"Supporting evidence: {'; '.join(h.get('supporting_evidence', []))} [{', '.join(h['citations'])}]")
        if analysis.get("contributing_factors"):
            out.append("Contributing factors: " + "; ".join(f"{f['factor']} ({f['direction']}): {f['evidence']}"
                                                             for f in analysis["contributing_factors"]))
        if analysis.get("impact", {}).get("narrative"):
            out.append("Impact: " + analysis["impact"]["narrative"])
        if analysis.get("data_limitations"):
            out.append("Data limitations: " + "; ".join(analysis["data_limitations"]))
    out.append("Recommended actions:")
    for r in recs:
        out.append(f"{r['step']}. {r['action']} (phase {r['phase']}{', requires change approval' if r.get('requires_change_approval') else ''}). "
                   f"Why: {r.get('rationale', '')} Verify: {r.get('verification', '')} [{', '.join(r['citations'])}]")
    if escalation:
        out.append(f"Escalation: {'needed, ' + escalation.get('team', '') if escalation.get('needed') else 'not needed'}. "
                   f"{escalation.get('reason', '')}")
    return "\n".join(out)


def render_a(answer: dict) -> str:
    out = [f"Summary: {answer['summary']}", "Likely causes:"]
    out += [f"- {c['cause']} [{', '.join(c['citations'])}]" for c in answer["likely_causes"]]
    out.append("Recommended actions:")
    out += [f"{r['step']}. {r['action']} Why: {r.get('rationale', '')} [{', '.join(r['citations'])}]"
            for r in answer["recommendations"]]
    return "\n".join(out)


def usage_stats(usage) -> dict:
    return {**usage.summary(), "repair_calls": sum(x["purpose"].endswith("_repair") for x in usage.calls),
            "calls_by_purpose": [x["purpose"] for x in usage.calls]}


# ---------------------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", default="")
    parser.add_argument("--cache", action="store_true", help="allow cached LLM replies (latency then not real)")
    args = parser.parse_args()
    use_system_certificates()
    s = get_settings()
    if not args.cache:
        s = s.model_copy(update={"llm_cache_enabled": False})
    c = ServiceContainer.build(s)
    if not (c.ready and c.llm.available):
        raise SystemExit(f"not ready ({c.missing}) or no LLM configured")
    cases = json.loads(RAG_GOLDEN.read_text(encoding="utf-8"))
    if args.ids:
        cases = [x for x in cases if x["id"] in args.ids.split(",")]
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "generations.json"
    results = json.loads(out_path.read_text(encoding="utf-8")) if (args.ids and out_path.exists()) else {}

    for case in cases:
        qid, q = case["id"], case["query"]
        rec = {"id": qid, "query": q}
        # ---- A: basic RAG
        CAP.reset()
        usage_box = {}
        orig_new_usage = c.llm.new_usage

        def tracked_usage():
            u = orig_new_usage()
            usage_box["u"] = u
            return u
        c.llm.new_usage = tracked_usage
        t0 = time.perf_counter()
        a = service.basic_recommend(c, q, None, None, 5)
        rec["A"] = {"latency_s": round(time.perf_counter() - t0, 1), "status": a["status"], "response": a,
                    "actual_output": render_a(a["answer"]), "retrieval_context": evidence_items(CAP.packs),
                    "usage": usage_stats(usage_box["u"])}
        # ---- C (and B = first pass)
        CAP.reset()
        t0 = time.perf_counter()
        r = service.run_troubleshoot(c, q, None, None, 5, s.max_revisions, True)
        c.llm.new_usage = orig_new_usage
        st = CAP.final_state
        first = CAP.judge_passes[0] if CAP.judge_passes else None
        rec["C"] = {"latency_s": round(time.perf_counter() - t0, 1), "status": r["status"], "response": r,
                    "actual_output": render_c(st.get("analysis"), r["recommendations"], r.get("escalation")),
                    "retrieval_context": evidence_items(CAP.packs), "usage": usage_stats(st["usage"]),
                    "fallback_events": [t["node"] for t in r["trace"] if t["status"] == "fallback"],
                    "final_degraded_steps": st.get("degraded_steps", []),
                    "judge_passes": [{k: p[k] for k in ("verdict", "scores", "issues")} for p in CAP.judge_passes],
                    "judge_state": {k: st.get(k) for k in JUDGE_STATE_KEYS}}
        if first and len(CAP.judge_passes) > 1:  # B differs from C only when a revision happened
            rec["B"] = {"actual_output": render_c(first["analysis"], first["recommendations"], first["escalation"]),
                        "retrieval_context": rec["C"]["retrieval_context"], "verdict": first["verdict"],
                        "scores": first["scores"]}
        results[qid] = rec
        cv = r.get("validation") or {}
        print(f"{qid} A {rec['A']['latency_s']:5.1f}s {a['status']:8} | C {rec['C']['latency_s']:6.1f}s {r['status']:8} "
              f"verdict={cv.get('verdict')} rev={cv.get('revisions')} calls={r['meta']['llm_calls']} "
              f"repairs={rec['C']['usage']['repair_calls']} fallbacks={rec['C']['fallback_events'] or '-'}", flush=True)
        out_path.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")  # checkpoint per case
    print(f"wrote {len(results)} cases to {out_path}")


if __name__ == "__main__":
    main()

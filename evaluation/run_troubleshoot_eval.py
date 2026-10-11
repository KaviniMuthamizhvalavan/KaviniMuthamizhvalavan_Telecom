"""End-to-end /troubleshoot measurement: latency, LLM usage and analyst/judge quality (Phase 8 verify).

Run from the repo root:  python -m evaluation.run_troubleshoot_eval [--ids G05,G09] [--cache]
- Runs the full multi-agent service in-process with the LLM cache OFF (true latency), for the 3 PRD queries and
  a spread of golden queries.
- Quality: the runtime judge's verdict/scores and the deterministic rule checks, plus an independent re-score of
  the same diagnosis by the evaluation model (EVAL_LLM_MODEL, default Claude Haiku 5.5) with the same rubric,
  because the runtime judge shares the model that wrote the diagnosis.
Uses the runtime and evaluation LLM APIs (about 5-9 calls per query). Never run during a demo.
"""
import argparse
import json
import time

import pandas as pd

from src.agents import judge_agent
from src.services import troubleshooting_service as service
from src.services.container import ServiceContainer
from src.services.llm_client import LLMClient, LLMError
from src.utils.config import PROJECT_ROOT, get_settings
from src.utils.net import use_system_certificates

GOLDEN = PROJECT_ROOT / "tests" / "test_cases" / "golden_queries.json"
OUT = PROJECT_ROOT / "evaluation" / "results" / "final" / "troubleshoot"
PRD_IDS = ["G17", "G18", "G19"]
SPREAD_IDS = ["G05", "G09", "G13", "G15", "G24"]
SCORE_KEYS = ["groundedness", "kpi_consistency", "actionability", "completeness"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", default=",".join(PRD_IDS + SPREAD_IDS))
    parser.add_argument("--cache", action="store_true", help="allow cached LLM replies (latency then not real)")
    args = parser.parse_args()
    use_system_certificates()
    s = get_settings()
    if not args.cache:
        s = s.model_copy(update={"llm_cache_enabled": False})
    c = ServiceContainer.build(s)
    if not c.ready or not c.llm.available:
        raise SystemExit(f"not ready (missing={c.missing}) or no LLM configured")
    indep = LLMClient(s.eval_settings(), model=s.eval_model)  # own limiter: may be a different provider

    captured = {}
    original = service.troubleshoot_response

    def capture(cc, state, *a, **kw):
        captured["state"] = state
        return original(cc, state, *a, **kw)
    service.troubleshoot_response = capture

    golden = {q["id"]: q for q in json.loads(GOLDEN.read_text(encoding="utf-8"))}
    rows, samples = [], {}
    for qid in args.ids.split(","):
        q = golden[qid]
        t0 = time.perf_counter()
        resp = service.run_troubleshoot(c, q["query"], None, None, 5, s.max_revisions, True)
        latency = (time.perf_counter() - t0) * 1000
        state, v = captured["state"], resp["validation"] or {}
        row = {"query_id": qid, "prd": qid in PRD_IDS, "status": resp["status"], "latency_s": round(latency / 1000, 1),
               "llm_calls": resp["meta"]["llm_calls"], "tokens": resp["meta"]["tokens_in"] + resp["meta"]["tokens_out"],
               "verdict": v.get("verdict"), "revisions": v.get("revisions"),
               "primary": resp["classification"]["primary_category"], "expected": q["expected_primary"],
               "rules_failed": ",".join(r["rule"] for r in v.get("rule_checks", []) if not r["passed"]),
               "n_recs": len(resp["recommendations"]), "degraded_steps": ",".join(state.get("degraded_steps", [])),
               "repair_calls": sum(x["purpose"].endswith("_repair") for x in state["usage"].calls),
               "fallbacks": len([x for x in state.get("degraded_steps", []) if x != "llm_unavailable"])}
        for t in resp["trace"]:
            row[f"ms_{t['node']}"] = row.get(f"ms_{t['node']}", 0) + t["ms"]
        for t in resp["trace"]:
            row[f"calls_{t['node']}"] = row.get(f"calls_{t['node']}", 0) + t["llm_calls"]
        row.update({f"judge_{k}": v.get("scores", {}).get(k) for k in SCORE_KEYS})
        if state.get("analysis") and state.get("recommendations"):
            try:
                iv = judge_agent.judge(indep, state, indep.new_usage())
                row.update({f"indep_{k}": iv["scores"][k] for k in SCORE_KEYS}, indep_verdict=iv["verdict"],
                           indep_issues=" | ".join(i["problem"] for i in iv["issues"])[:400])
            except LLMError as exc:
                row["indep_verdict"] = f"error: {type(exc).__name__}"
        rows.append(row)
        samples[qid] = resp
        print(f"{qid} {resp['status']:9} {row['latency_s']:6.1f}s calls={row['llm_calls']} tokens={row['tokens']} "
              f"repairs={row['repair_calls']} fallbacks={row['fallbacks']} "
              f"verdict={row['verdict']} rev={row['revisions']} judge_g={row['judge_groundedness']} "
              f"indep={row.get('indep_verdict')} indep_g={row.get('indep_groundedness')} "
              f"rules_failed={row['rules_failed'] or '-'} degraded={row['degraded_steps'] or '-'}", flush=True)

    df = pd.DataFrame(rows)
    node_cols = [col for col in df.columns if col.startswith("ms_")]
    summary = {
        "runs": len(df), "cache": args.cache, "model": s.runtime_model, "judge_model": s.judge_llm_model or s.runtime_model,
        "independent_judge": s.eval_model,
        "reasoning": {"classifier": s.classifier_reasoning, "analyst": s.analyst_reasoning,
                      "recommender": s.recommender_reasoning, "judge": s.judge_reasoning},
        "latency_s": {"p50": round(df.latency_s.median(), 1), "p95": round(df.latency_s.quantile(0.95), 1),
                      "max": round(df.latency_s.max(), 1),
                      "prd_max": round(df[df.prd].latency_s.max(), 1) if df.prd.any() else None},
        "within_30s": int((df.latency_s <= 30).sum()),
        "node_mean_s": {col[3:]: round(df[col].mean() / 1000, 1) for col in node_cols},
        "llm_calls_mean": round(df.llm_calls.mean(), 1), "llm_calls_max": int(df.llm_calls.max()),
        "tokens_mean": int(df.tokens.mean()), "tokens_max": int(df.tokens.max()),
        "repair_calls_total": int(df.repair_calls.sum()), "fallbacks_total": int(df.fallbacks.sum()),
        "node_llm_calls_mean": {col[6:]: round(df[col].mean(), 2) for col in df.columns if col.startswith("calls_")},
        "status": df.status.value_counts().to_dict(), "verdict": df.verdict.value_counts().to_dict(),
        "revision_rate": round(float((df.revisions > 0).mean()), 2),
        "classification_correct": int((df.primary == df.expected).sum()),
        "runtime_judge_mean": {k: round(df[f"judge_{k}"].mean(), 2) for k in SCORE_KEYS},
        "independent_judge_mean": {k: round(df[f"indep_{k}"].mean(), 2) for k in SCORE_KEYS if f"indep_{k}" in df},
        "independent_verdict": df["indep_verdict"].value_counts().to_dict() if "indep_verdict" in df else {},
        "rule_failures": df.rules_failed[df.rules_failed != ""].value_counts().to_dict(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "troubleshoot_runs.csv", index=False)
    (OUT / "troubleshoot_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (OUT / "troubleshoot_samples.json").write_text(json.dumps(samples, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()

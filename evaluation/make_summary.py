"""Build evaluation/results/final/summary.md + summary.json + run_config.json from the result files (plan §11.9).

Run from the repo root:  python -m evaluation.make_summary
Every number in summary.md is read from a file under evaluation/results/final/ (or the frozen Phase 8 baseline in
evaluation/results/runs/troubleshoot_run2_baseline/). Missing inputs are reported as "not run", never invented.
"""
import json
import subprocess
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.utils.config import PROJECT_ROOT, get_settings

F = PROJECT_ROOT / "evaluation" / "results" / "final"
BASELINE = PROJECT_ROOT / "evaluation" / "results" / "runs" / "troubleshoot_run2_baseline" / "troubleshoot_summary.json"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def load_csv(path):
    return pd.read_csv(path) if path.exists() else None


def status(value, target, higher=True):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "not run"
    return "PASS" if (value >= target if higher else value <= target) else "FAIL"


def fmt(v, digits=3):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    return f"{v:.{digits}f}" if isinstance(v, (float, np.floating)) else str(v)


# ---------------------------------------------------------------------------- end-to-end stats from generations
def e2e_stats(gens: dict) -> tuple[dict, pd.DataFrame]:
    rows = []
    for qid, r in gens.items():
        c, a = r["C"], r["A"]
        v = c["response"].get("validation") or {}
        rows.append({"id": qid, "C_latency_s": c["latency_s"], "A_latency_s": a["latency_s"],
                     "C_status": c["status"], "A_status": a["status"], "C_verdict": v.get("verdict"),
                     "C_revisions": v.get("revisions"), "C_llm_calls": c["usage"]["llm_calls"],
                     "C_tokens": c["usage"]["tokens_in"] + c["usage"]["tokens_out"],
                     "A_tokens": a["usage"]["tokens_in"] + a["usage"]["tokens_out"],
                     "C_repairs": c["usage"]["repair_calls"], "A_repairs": a["usage"]["repair_calls"],
                     "C_fallback_events": len(c["fallback_events"]),
                     "C_json_fallbacks": sum("StructuredOutputError" in w for w in c["response"]["warnings"])
                                         + sum(1 for t in c["response"]["trace"] if t["status"] == "fallback"
                                               and t["node"] not in c["final_degraded_steps"]),
                     "C_budget_fallbacks": sum("budget" in w for w in c["response"]["warnings"]),
                     "C_agent_nodes": sum(1 for t in c["response"]["trace"]
                                          if t["node"] in ("classify", "analyze", "recommend", "judge")),
                     "C_final_degraded": bool(c["final_degraded_steps"]),
                     "C_primary": c["response"]["classification"]["primary_category"],
                     "C_low_confidence": any(w.startswith("Low-confidence") for w in c["response"]["warnings"])})
    df = pd.DataFrame(rows)
    calls = int(df.C_llm_calls.sum())
    s = {"n": len(df),
         "C_latency_s": {"median": round(df.C_latency_s.median(), 1), "p95": round(df.C_latency_s.quantile(0.95), 1),
                         "max": round(df.C_latency_s.max(), 1), "min": round(df.C_latency_s.min(), 1)},
         "A_latency_s": {"median": round(df.A_latency_s.median(), 1), "p95": round(df.A_latency_s.quantile(0.95), 1)},
         "C_llm_calls": {"mean": round(df.C_llm_calls.mean(), 1), "max": int(df.C_llm_calls.max())},
         "C_tokens": {"mean": int(df.C_tokens.mean()), "max": int(df.C_tokens.max())},
         "A_tokens_mean": int(df.A_tokens.mean()),
         "C_repair_calls": int(df.C_repairs.sum()), "A_repair_calls": int(df.A_repairs.sum()),
         "C_first_attempt_invalid_rate": round(df.C_repairs.sum() / max(calls - df.C_repairs.sum(), 1), 3),
         "C_fallback_events": int(df.C_fallback_events.sum()),
         "C_json_fallbacks": int(df.C_json_fallbacks.sum()), "C_budget_fallbacks": int(df.C_budget_fallbacks.sum()),
         "C_agent_node_runs": int(df.C_agent_nodes.sum()),
         "C_json_failure_rate": round(df.C_json_fallbacks.sum() / max(df.C_agent_nodes.sum(), 1), 3),
         "C_runs_final_degraded": int(df.C_final_degraded.sum()),
         "C_status": df.C_status.value_counts().to_dict(), "A_status": df.A_status.value_counts().to_dict(),
         "C_verdicts": df.C_verdict.value_counts().to_dict(), "C_revision_rate": round(float((df.C_revisions > 0).mean()), 2),
         "C_low_confidence_runs": df[df.C_low_confidence].id.tolist()}
    return s, df


def _git_sha() -> str | None:
    """Commit the evaluated code was at (uncommitted changes are not reflected)."""
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True,
                              timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def main() -> None:
    s = get_settings()
    rows, sections = [], []

    # ---- retrieval
    ret = load_csv(F / "retrieval" / "retrieval_metrics.csv")
    if ret is not None:
        r = ret.set_index("mode")
        best_single = max(r.loc["bm25", "ndcg@10"], r.loc["dense", "ndcg@10"])
        rows += [("Retrieval", "Filter compliance (hybrid_rerank)", r.loc["hybrid_rerank", "filter_compliance"], ">= 1.0",
                  status(r.loc["hybrid_rerank", "filter_compliance"], 1.0)),
                 ("Retrieval", "Hit@5 (hybrid_rerank)", r.loc["hybrid_rerank", "hit@5"], ">= 0.90",
                  status(r.loc["hybrid_rerank", "hit@5"], 0.90)),
                 ("Retrieval", "nDCG@10 hybrid vs best single mode", r.loc["hybrid", "ndcg@10"], f">= {best_single:.3f}",
                  status(r.loc["hybrid", "ndcg@10"], best_single)),
                 ("Retrieval", "p95 latency, hybrid_rerank (ms)", r.loc["hybrid_rerank", "latency_p95_ms"], "<= 300",
                  status(r.loc["hybrid_rerank", "latency_p95_ms"], 300, higher=False))]
    comp = load_json(F / "components" / "component_metrics.json")
    if comp:
        rows.append(("KB retrieval", "Hit@3 expected category", comp["kb_retrieval"]["hit@3_expected"], ">= 0.90",
                     status(comp["kb_retrieval"]["hit@3_expected"], 0.90)))
        pr = comp["prioritization"]
        rows += [("Prioritization", "Scenario exact agreement", pr["exact"], ">= 0.80", status(pr["exact"], 0.80)),
                 ("Prioritization", "Scenario within one level", pr["within_1"], ">= 1.0", status(pr["within_1"], 1.0))]

    # ---- classifier
    cls = load_csv(F / "classification" / "classification_metrics.csv")
    crep = load_json(F / "classification" / "classification_report.json")
    if cls is not None:
        llm_row = cls[cls.system.str.startswith("llm")].iloc[0]
        llm_key = llm_row.system
        # AICredits cannot switch thinking off, so "reasoning off" is claimed only where it holds
        clabel = ("Classifier (LLM, reasoning off)" if s.llm_provider == "anthropic" and not s.classifier_reasoning
                  else "Classifier (LLM)")
        rows += [(clabel, "Primary accuracy", llm_row.primary_acc, ">= 0.80",
                  status(llm_row.primary_acc, 0.80)),
                 (clabel, "Macro-F1", crep[llm_key]["macro_f1"] if crep else None, ">= 0.75",
                  status(crep[llm_key]["macro_f1"] if crep else None, 0.75)),
                 (clabel, "Filter exact match", llm_row.filters_exact, ">= 0.85",
                  status(llm_row.filters_exact, 0.85)),
                 (clabel, "Out-of-scope detection (n=1)", llm_row.off_topic_flagged, ">= 0.90",
                  status(llm_row.off_topic_flagged, 0.90))]
    gr = load_json(F / "guardrails" / "guardrail_metrics.json")
    if gr:
        rows += [("Guardrails", "Block rate", gr["blocked_rate"], ">= 0.90", status(gr["blocked_rate"], 0.90)),
                 ("Guardrails", "False-positive rate", gr["false_positive_rate"], "<= 0.05",
                  status(gr["false_positive_rate"], 0.05, higher=False))]
    fr, perf = load_json(F / "ml" / "fault_risk_metrics.json"), load_json(F / "ml" / "performance_metrics.json")
    if fr:
        rows.append(("Fault-risk model", "ROC-AUC (holdout)", fr["roc_auc"], ">= 0.85", status(fr["roc_auc"], 0.85)))
    if perf:
        rows.append(("Performance model", "R2 (holdout)", perf["r2"], ">= 0.25", status(perf["r2"], 0.25)))
    fb = load_json(F / "feedback" / "feedback_sim_summary.json")
    if fb:
        rows += [("Feedback loop", "nDCG@10 delta, voted queries", fb["feedback"]["delta_mean"], "> 0",
                  "PASS" if fb["feedback"]["delta_mean"] > 0 else "FAIL"),
                 ("Feedback loop", "Control queries regressed", fb["control"]["regressed"], "0",
                  "PASS" if fb["control"]["regressed"] == 0 else "FAIL")]

    # ---- end to end
    gens = load_json(F / "deepeval" / "generations.json")
    e2e, e2e_df = (e2e_stats(gens) if gens else (None, None))
    if e2e:
        (F / "e2e").mkdir(exist_ok=True)
        e2e_df.to_csv(F / "e2e" / "latency.csv", index=False)
        (F / "e2e" / "e2e_summary.json").write_text(json.dumps(e2e, indent=2), encoding="utf-8")
        rows += [("End to end (C)", "/troubleshoot median latency (s)", e2e["C_latency_s"]["median"], "<= 60 (internal)",
                  status(e2e["C_latency_s"]["median"], 60, higher=False)),
                 ("End to end (C)", "JSON failures after repair, per agent call", e2e["C_json_failure_rate"], "<= 0.02",
                  status(e2e["C_json_failure_rate"], 0.02, higher=False)),
                 ("End to end (C)", "Runs ending degraded (any cause)", e2e["C_runs_final_degraded"] / e2e["n"], "reported",
                  "info")]
    ret_search = ret.set_index("mode").loc["hybrid_rerank", "latency_p95_ms"] / 1000 if ret is not None else None
    if ret_search is not None:
        rows.append(("End to end", "/search p95 latency (s, retrieval core)", ret_search, "<= 1.0",
                     status(ret_search, 1.0, higher=False)))

    # ---- DeepEval
    de = load_csv(F / "deepeval" / "deepeval_summary.csv")
    if de is not None:
        for _, d in de[de.system == "C"].iterrows():
            target = 0.5 if d.metric == "contextual_relevancy" else 0.7
            rows.append(("DeepEval, system C (mean score)", d.metric, d["mean"], f">= {target}", status(d["mean"], target)))
    jm = load_json(F / "judge_meta" / "judge_meta_summary.json")
    if jm:
        rows.append(("Runtime judge", "Seeded-error detection rate", jm["detection_rate"], ">= 0.80",
                     status(jm["detection_rate"], 0.80)))

    table = pd.DataFrame(rows, columns=["Component", "Metric", "Value", "Target", "Status"])
    lines = ["# Phase 11 evaluation summary", "",
             f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by `python -m evaluation.make_summary`. "
             f"Every number below is read from a file in `{F.relative_to(PROJECT_ROOT).as_posix()}/`.", "",
             "## Headline metrics vs targets", "", "| Component | Metric | Value | Target | Status |", "|---|---|---|---|---|"]
    lines += [f"| {r.Component} | {r.Metric} | {fmt(r.Value)} | {r.Target} | {r.Status} |" for r in table.itertuples()]
    lines += ["", f"Totals: {int((table.Status == 'PASS').sum())} PASS, {int((table.Status == 'FAIL').sum())} FAIL, "
                  f"{int((table.Status == 'not run').sum())} not run, {int((table.Status == 'info').sum())} informational."]

    if e2e:
        base = load_json(BASELINE)
        lines += ["", "## End-to-end runs (system C, LLM cache off) vs the frozen Phase 8 baseline", "",
                  "| Metric | Phase 11 (n=%d) | Phase 8 baseline (n=%s) |" % (e2e["n"], base["runs"] if base else "n/a"),
                  "|---|---|---|",
                  f"| Latency median / p95 / max (s) | {e2e['C_latency_s']['median']} / {e2e['C_latency_s']['p95']} / {e2e['C_latency_s']['max']} | "
                  + (f"{base['latency_s']['p50']} / {base['latency_s']['p95']} / {base['latency_s']['max']} |" if base else "n/a |"),
                  f"| LLM calls per run, mean / max | {e2e['C_llm_calls']['mean']} / {e2e['C_llm_calls']['max']} | "
                  + (f"{base['llm_calls_mean']} / {base.get('llm_calls_max', 'n/a')} |" if base else "n/a |"),
                  f"| Tokens per run, mean / max | {e2e['C_tokens']['mean']:,} / {e2e['C_tokens']['max']:,} | "
                  + (f"{base['tokens_mean']:,} / {base.get('tokens_max', 'n/a'):,} |" if base and base.get('tokens_max') else "n/a |"),
                  f"| Repair calls (total) | {e2e['C_repair_calls']} | {base.get('repair_calls_total', 'n/a') if base else 'n/a'} |",
                  f"| Fallback events (any node, incl. recovered) | {e2e['C_fallback_events']} | {base.get('fallbacks_total', 'n/a') if base else 'n/a'} |",
                  f"| Runs ending degraded | {e2e['C_runs_final_degraded']} (JSON {e2e['C_json_fallbacks']}, call budget {e2e['C_budget_fallbacks']}) | {base['status'].get('degraded', 0) if base else 'n/a'} |",
                  f"| Status | {e2e['C_status']} | {base['status'] if base else 'n/a'} |",
                  f"| Verdicts | {e2e['C_verdicts']} | {base['verdict'] if base else 'n/a'} |",
                  f"| Revision rate | {e2e['C_revision_rate']} | {base['revision_rate'] if base else 'n/a'} |",
                  "", f"System A (basic RAG, 1 call): median {e2e['A_latency_s']['median']} s, p95 {e2e['A_latency_s']['p95']} s, "
                      f"{e2e['A_tokens_mean']:,} tokens per run, {e2e['A_repair_calls']} repair calls, status {e2e['A_status']}.",
                  f"Low-confidence (validator fail) runs: {e2e['C_low_confidence_runs'] or 'none'}."]
    if de is not None:
        piv = de.pivot_table(index="metric", columns="system", values="mean")
        pr_ = de.pivot_table(index="metric", columns="system", values="pass_rate")
        systems = [x for x in ("A", "B", "C") if x in piv.columns]
        lines += ["", "## DeepEval (judge: %s) mean score / pass rate per system" % s.eval_model, "",
                  "| Metric | " + " | ".join(systems) + " |", "|---|" + "---|" * len(systems)]
        for m in piv.index:
            lines.append(f"| {m} | " + " | ".join(f"{fmt(piv.loc[m, x], 2)} / {fmt(pr_.loc[m, x], 2)}" for x in systems) + " |")
        errs = de.groupby("system").errors.sum().to_dict()
        lines += ["", f"Metric errors (judge failures, recorded not hidden): {errs}. "
                      "B is evaluated only where C revised (elsewhere B is identical to C)."]
    if jm:
        lines += ["", "## Runtime judge meta-evaluation", "",
                  f"Seeded errors detected (verdict fail): {jm['detection_rate']} on {jm['n_seeded']} seeded diagnoses "
                  f"(bases {', '.join(jm['bases'])}); detected and matched to the seeded problem: {jm['detected_and_matched_rate']}. "
                  f"Control false alarms: {jm['control_false_alarms']} of {jm['controls']}.", "",
                  "| Seeded error | Detected | Matched |", "|---|---|---|"]
        lines += [f"| {k} | {fmt(v['detected'], 2)} | {fmt(v['matched'], 2)} |" for k, v in jm["by_error"].items()]
        if jm.get("agreement"):
            lines.append(f"\nSpearman(runtime groundedness, DeepEval faithfulness C) = {jm['agreement']['spearman']} "
                         f"(n={jm['agreement']['n']}).")
        if jm.get("revision_effectiveness"):
            re_ = jm["revision_effectiveness"]
            lines.append(f"Revision effectiveness: DeepEval faithfulness before (B) {re_['faithfulness_before_B']} vs after (C) "
                         f"{re_['faithfulness_after_C']} on {re_['n_revised']} revised runs.")
    (F / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (F / "summary.json").write_text(table.to_json(orient="records", indent=2), encoding="utf-8")

    manifest = load_json(s.artifacts_dir / "manifest.json") or {}
    from src.agents.graph import PROMPT_VERSIONS
    run_config = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_sha": _git_sha(),
                  "dataset": {"source": s.data_source, "sha256": manifest.get("cases", {}).get("dataset_sha256"),
                              "cases": manifest.get("cases", {}).get("cases")},
                  "models": {"runtime": s.runtime_model, "runtime_provider": s.llm_provider,
                             "runtime_judge": s.judge_llm_model or s.runtime_model,
                             "eval_judge": s.eval_model, "eval_judge_provider": s.eval_llm_provider,
                             "embedding": s.embedding_model},
                  "reasoning": {"classifier": s.classifier_reasoning, "analyst": s.analyst_reasoning,
                                "recommender": s.recommender_reasoning, "judge": s.judge_reasoning,
                                "agent_allowance": s.agent_reasoning_allowance, "default_allowance": s.llm_reasoning_allowance},
                  "prompts": PROMPT_VERSIONS, "narrative_template": manifest.get("cases", {}).get("template_version"),
                  "retrieval": {"top_k": s.top_k, "candidate_k": s.candidate_k, "rrf_k": s.rrf_k, "w_dense": s.w_dense,
                                "w_sparse": s.w_sparse, "rerank_symptom_weight": s.rerank_symptom_weight,
                                "rerank_feedback_weight": s.rerank_feedback_weight},
                  "max_revisions": s.max_revisions, "max_tokens_per_run": s.max_tokens_per_run}
    (F / "run_config.json").write_text(json.dumps(run_config, indent=2), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

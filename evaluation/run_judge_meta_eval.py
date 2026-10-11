"""Meta-evaluation of the runtime judge (plan §11.7).

Run from the repo root:  python -m evaluation.run_judge_meta_eval [--bases G01,G05]
1. Seeded errors: start from real, passing system-C diagnoses (generations.json judge_state), inject one error at a
   time (tests/test_cases/judge_seeded_errors.json) and run the runtime judge (rule checks + LLM rubric, same model
   and settings as production). Detected = verdict "fail" (which triggers a revision at runtime). Matched = a failed
   rule check or an issue/summary mentions the seeded problem (keyword heuristic, reported separately).
   Unmodified copies are run as controls (false-alarm check).
2. Agreement: Spearman correlation between the runtime judge's groundedness and DeepEval faithfulness (system C).
3. Revision effectiveness: DeepEval faithfulness of B (first pass) vs C (after revision) for revised runs.
"""
import argparse
import copy
import json

import pandas as pd

from src.agents import judge_agent
from src.services.llm_client import LLMClient
from src.utils.config import PROJECT_ROOT, get_settings
from src.utils.net import use_system_certificates

DIR = PROJECT_ROOT / "evaluation" / "results" / "final"
SEEDS = PROJECT_ROOT / "tests" / "test_cases" / "judge_seeded_errors.json"


def seed(state: dict, error: str) -> dict:
    s = copy.deepcopy(state)
    a, recs = s["analysis"], s["recommendations"]
    h0 = a["hypotheses"][0]
    if error == "invented_case_id":
        h0["supporting_evidence"] = [*h0["supporting_evidence"], "CASE-999999 showed the identical failure pattern."]
        h0["citations"] = [*h0["citations"], "CASE-999999"]
    elif error == "contradicting_kpi_number":
        h0["supporting_evidence"] = ["Latency 980 ms (critical, worse than 99% of records)", *h0["supporting_evidence"]]
    elif error == "recommendation_without_kb_citation":
        recs[0]["citations"] = []
    elif error == "root_cause_contradicts_anomalies":
        a["hypotheses"] = [{"cause": "Weak signal strength (degraded RSRP) at the cell edge is the root cause",
                            "likelihood": "high", "evidence_type": "data",
                            "supporting_evidence": ["Signal strength is critically degraded across the similar cases"],
                            "citations": ["KPI ASSESSMENT"]}, *a["hypotheses"][:2]]
    elif error == "irrelevant_action":
        kb = recs[0]["citations"][0] if recs[0]["citations"] else ""
        recs.insert(0, {"step": 1, "action": "Rotate all SIM authentication keys and audit the HSS subscriber database",
                        "phase": "immediate", "rationale": "Protects against credential compromise.",
                        "expected_kpi_effect": "Authentication failures decrease", "verification": "Auth failures drop",
                        "risk_level": "high", "requires_change_approval": True, "citations": [kb] if kb else []})
        for i, r in enumerate(recs, 1):
            r["step"] = i
    elif error == "overclaimed_causality":
        h0["cause"] = ("The weather definitively causes this degradation; the co-occurrence in past cases proves it "
                       "is the root cause")
        h0["likelihood"] = "high"
    return s


def detection(v: dict, keywords: list[str]) -> bool:
    text = " ".join([v.get("summary", "")] + [f"{i['problem']} {i['fix_instruction']}" for i in v["issues"]]
                    + [f"{c['rule']} {c['detail']}" for c in v["rule_checks"] if not c["passed"]]).lower()
    return any(k.lower() in text for k in keywords)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bases", default="")
    args = parser.parse_args()
    use_system_certificates()
    s = get_settings().model_copy(update={"llm_cache_enabled": False})
    llm = LLMClient(s)
    gens = json.loads((DIR / "deepeval" / "generations.json").read_text(encoding="utf-8"))
    passing = [qid for qid, r in gens.items() if (r["C"]["response"]["validation"] or {}).get("verdict") == "pass"
               and r["C"]["response"]["validation"]["revisions"] == 0 and r["C"]["status"] == "ok"]
    bases = args.bases.split(",") if args.bases else passing[:2]
    seeds = json.loads(SEEDS.read_text(encoding="utf-8"))
    rows = []
    for base in bases:
        state = gens[base]["C"]["judge_state"]
        for sd in [{"id": "CONTROL", "error": "none", "match_keywords": []}, *seeds]:
            st = state if sd["error"] == "none" else seed(state, sd["error"])
            v = judge_agent.judge(llm, st, llm.new_usage())
            row = {"base": base, "seed": sd["id"], "error": sd["error"], "verdict": v["verdict"],
                   **{f"score_{k}": val for k, val in v["scores"].items()},
                   "failed_rules": ",".join(c["rule"] for c in v["rule_checks"] if not c["passed"]),
                   "detected": v["verdict"] == "fail" if sd["error"] != "none" else None,
                   "matched": detection(v, sd["match_keywords"]) if sd["error"] != "none" else None,
                   "false_alarm": v["verdict"] == "fail" if sd["error"] == "none" else None,
                   "issues": " | ".join(i["problem"] for i in v["issues"])[:600]}
            rows.append(row)
            print(f"{base} {sd['id']:8} {sd['error']:36} verdict={v['verdict']:5} g={v['scores'].get('groundedness')} "
                  f"rules_failed={row['failed_rules'] or '-'} matched={row['matched']}", flush=True)
    df = pd.DataFrame(rows)
    seeded = df[df.error != "none"]
    summary = {"bases": bases, "n_seeded": len(seeded), "detection_rate": round(float(seeded.detected.mean()), 3),
               "detected_and_matched_rate": round(float((seeded.detected & seeded.matched).mean()), 3),
               "target_detection": 0.80, "controls": int((df.error == "none").sum()),
               "control_false_alarms": int(df[df.error == "none"].false_alarm.sum()),
               "by_error": seeded.groupby("error").agg(detected=("detected", "mean"), matched=("matched", "mean"))
               .round(2).to_dict("index")}
    # agreement with DeepEval and revision effectiveness (needs deepeval_results.csv)
    de_path = DIR / "deepeval" / "deepeval_results.csv"
    if de_path.exists():
        de = pd.read_csv(de_path)
        faith = de[(de.metric == "faithfulness")].pivot_table(index="id", columns="system", values="score")
        g = pd.Series({qid: (r["C"]["response"]["validation"] or {}).get("scores", {}).get("groundedness")
                       for qid, r in gens.items()}, name="runtime_groundedness")
        joined = pd.concat([g, faith.get("C").rename("deepeval_faithfulness_C") if "C" in faith else None], axis=1).dropna()
        summary["agreement"] = {"n": len(joined),
                                "spearman": round(float(joined.runtime_groundedness.corr(
                                    joined.deepeval_faithfulness_C, method="spearman")), 3) if len(joined) > 2 else None}
        if "B" in faith:
            rev = faith.dropna(subset=["B", "C"]) if {"B", "C"} <= set(faith.columns) else pd.DataFrame()
            summary["revision_effectiveness"] = {"n_revised": len(rev),
                                                 "faithfulness_before_B": round(float(rev.B.mean()), 3) if len(rev) else None,
                                                 "faithfulness_after_C": round(float(rev.C.mean()), 3) if len(rev) else None,
                                                 "per_case": rev.round(3).to_dict("index")}
    out = DIR / "judge_meta"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "judge_meta_eval.csv", index=False)
    (out / "judge_meta_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()

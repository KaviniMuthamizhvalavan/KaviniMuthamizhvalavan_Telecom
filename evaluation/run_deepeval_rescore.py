"""Evaluation-only re-score with a corrected scoring input (Phase 11 follow-up). Production code is untouched.

Correction: the scored answer (`actual_output`) now includes the similar-case list that the API returns
(`similar_cases`). The first Phase 11 scoring rendered only the analysis and actions, so queries such as
"What similar network conditions have occurred before?" were judged without the cases the system returned.
Nothing else changes: same generations (no new system runs), same retrieval context, reference answers, metrics,
thresholds and judge. Contextual precision/recall/relevancy do not read `actual_output`, so they must come out
identical (their judge calls are served from the evaluation cache); they are re-run only to prove that.

The original results (evaluation/results/final/deepeval/) are read-only here; outputs go to deepeval_v2/.
Run from the repo root:  python -m evaluation.run_deepeval_rescore [--workers 6]
"""
import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from deepeval.test_case import LLMTestCase

from evaluation.deepeval_judge import OpenAICompatibleJudge
from evaluation.run_deepeval import THRESHOLDS, make_metrics, measure_one
from src.utils.config import PROJECT_ROOT
from src.utils.net import use_system_certificates

V1 = PROJECT_ROOT / "evaluation" / "results" / "final" / "deepeval"
V2 = PROJECT_ROOT / "evaluation" / "results" / "final" / "deepeval_v2"
RAG_GOLDEN = PROJECT_ROOT / "tests" / "test_cases" / "rag_golden.json"
ANSWER_DEPENDENT = ["faithfulness", "answer_relevancy", "actionability_geval", "diagnosis_validity_geval"]


def case_list(similar_cases: list[dict]) -> str:
    """The similar cases exactly as the API returned them (id, type, location, conditions, priority, summary)."""
    lines = ["Similar past cases (returned by the API):"]
    for c in similar_cases:
        lines.append(f"{c['rank']}. [{c['case_id']}] {c['primary_category']} | {c['state']}, {c['season']}, "
                     f"{c['weather']} | priority {c['priority']} | {c['summary']}")
    return "\n".join(lines)


def corrected_output(rec: dict, system: str) -> str:
    """Prepend the API's similar-case list to the originally scored answer (B uses C's cases: same retrieval)."""
    source = rec["C" if system == "B" else system]["response"]
    return case_list(source["similar_cases"]) + "\n\n" + rec[system]["actual_output"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--systems", default="A,C,B")
    args = parser.parse_args()
    use_system_certificates()
    gens = json.loads((V1 / "generations.json").read_text(encoding="utf-8"))
    golden = {g["id"]: g for g in json.loads(RAG_GOLDEN.read_text(encoding="utf-8"))}
    V2.mkdir(parents=True, exist_ok=True)
    inputs = {qid: {s: corrected_output(rec, s) for s in args.systems.split(",") if s in rec} for qid, rec in gens.items()}
    (V2 / "scoring_inputs.json").write_text(json.dumps(inputs, indent=1), encoding="utf-8")

    judge = OpenAICompatibleJudge()
    rows, lock = [], threading.Lock()
    out_csv = V2 / "deepeval_results.csv"

    def score(job):
        qid, system = job
        rec = gens[qid]
        tc = LLMTestCase(input=rec["query"], actual_output=inputs[qid][system],
                         expected_output=golden[qid]["reference_answer"],
                         retrieval_context=rec[system]["retrieval_context"])
        out = []
        for name, metric in make_metrics(judge).items():
            row = {"id": qid, "system": system, "metric": name, "threshold": THRESHOLDS[name], **measure_one(metric, tc)}
            out.append(row)
            print(f"{qid} {system} {name:26} score={row['score']} {row['error'][:80]}", flush=True)
        with lock:
            rows.extend(out)
            pd.DataFrame(rows).to_csv(out_csv, index=False)

    jobs = [(qid, s) for qid in inputs for s in inputs[qid]]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(score, jobs))
    compare()
    (V2 / "judge_usage.json").write_text(json.dumps(judge.usage.summary(), indent=2), encoding="utf-8")
    print("judge usage:", judge.usage.summary())


def compare() -> pd.DataFrame:
    """Per case and metric: v1 (original input) vs v2 (corrected input), plus a per-system summary."""
    v1 = pd.read_csv(V1 / "deepeval_results.csv")[["id", "system", "metric", "score", "success"]]
    v2 = pd.read_csv(V2 / "deepeval_results.csv")[["id", "system", "metric", "score", "success", "error"]]
    m = v1.merge(v2, on=["id", "system", "metric"], suffixes=("_v1", "_v2"))
    m["delta"] = (m.score_v2 - m.score_v1).round(4)
    m["answer_dependent"] = m.metric.isin(ANSWER_DEPENDENT)
    m.to_csv(V2 / "comparison_per_case.csv", index=False)
    summ = (m.groupby(["system", "metric"])
            .agg(n=("delta", "size"), mean_v1=("score_v1", "mean"), mean_v2=("score_v2", "mean"),
                 mean_delta=("delta", "mean"), changed=("delta", lambda d: int((d.abs() > 1e-9).sum())),
                 pass_v1=("success_v1", lambda s: s.dropna().astype(float).mean()),
                 pass_v2=("success_v2", lambda s: s.dropna().astype(float).mean()),
                 errors_v2=("error", lambda e: int((e.fillna("") != "").sum())))
            .round(3).reset_index())
    summ.to_csv(V2 / "comparison_summary.csv", index=False)
    print(summ.to_string(index=False))
    return summ


if __name__ == "__main__":
    main()

"""Phase 11 DeepEval scoring (plan §11.5) over evaluation/results/final/deepeval/generations.json.

Run from the repo root:  python -m evaluation.run_deepeval [--systems A,C,B] [--ids G01]
Systems: A = basic RAG, C = multi-agent with the judge loop, B = C's first pass (only where C revised; elsewhere
B == C). Judge: EVAL_LLM_MODEL (default claude-haiku-5-5) through evaluation/deepeval_judge.py. Each metric is measured on its
own and errors are recorded, so one failed metric never hides the others.
Outputs: deepeval_results.csv (per case x metric, with reasons), deepeval_summary.csv (per system x metric).
"""
import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from deepeval.metrics import (AnswerRelevancyMetric, ContextualPrecisionMetric, ContextualRecallMetric,
                              ContextualRelevancyMetric, FaithfulnessMetric, GEval)
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

from evaluation.deepeval_judge import OpenAICompatibleJudge
from src.utils.config import PROJECT_ROOT
from src.utils.net import use_system_certificates

DIR = PROJECT_ROOT / "evaluation" / "results" / "final" / "deepeval"
RAG_GOLDEN = PROJECT_ROOT / "tests" / "test_cases" / "rag_golden.json"
P = LLMTestCaseParams

ACTIONABILITY_STEPS = [
    "Check that the recommendations are concrete operator actions for this network problem, not generic advice.",
    "Check that they are ordered sensibly by urgency: containment and diagnostics before longer-term fixes.",
    "Check that each action states how to verify it worked, such as which KPI should recover.",
    "Check that disruptive changes are flagged as needing change approval and that escalation is decided.",
    "Penalize vague, duplicated or irrelevant actions and actions unrelated to the described symptoms.",
]
DIAGNOSIS_STEPS = [
    "Compare each stated cause with the KPI evidence, similar cases and runbook content in the retrieval context.",
    "Penalize causes that the evidence does not support or that contradict the reported KPI anomalies.",
    "Penalize causal claims made from co-occurrence or correlation alone.",
    "Reward stating uncertainty and data limitations where the evidence is indirect.",
]


def make_metrics(judge) -> dict:
    return {
        "faithfulness": FaithfulnessMetric(threshold=0.7, model=judge, include_reason=True),
        "answer_relevancy": AnswerRelevancyMetric(threshold=0.7, model=judge, include_reason=True),
        "contextual_relevancy": ContextualRelevancyMetric(threshold=0.5, model=judge, include_reason=True),
        "contextual_precision": ContextualPrecisionMetric(threshold=0.7, model=judge, include_reason=True),
        "contextual_recall": ContextualRecallMetric(threshold=0.7, model=judge, include_reason=True),
        "actionability_geval": GEval(name="Recommendation Actionability", threshold=0.7, model=judge,
                                     evaluation_steps=ACTIONABILITY_STEPS,
                                     evaluation_params=[P.INPUT, P.ACTUAL_OUTPUT]),
        "diagnosis_validity_geval": GEval(name="Diagnosis Validity", threshold=0.7, model=judge,
                                          evaluation_steps=DIAGNOSIS_STEPS,
                                          evaluation_params=[P.INPUT, P.ACTUAL_OUTPUT, P.RETRIEVAL_CONTEXT]),
    }


THRESHOLDS = {"faithfulness": 0.7, "answer_relevancy": 0.7, "contextual_relevancy": 0.5, "contextual_precision": 0.7,
              "contextual_recall": 0.7, "actionability_geval": 0.7, "diagnosis_validity_geval": 0.7}


def measure_one(metric, tc) -> dict:
    t0 = time.perf_counter()
    try:
        metric.measure(tc)
        row = {"score": round(float(metric.score), 4), "success": bool(metric.success),
               "reason": (metric.reason or "")[:1500], "error": ""}
    except Exception as exc:  # recorded, never hidden
        row = {"score": None, "success": None, "reason": "", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    row["seconds"] = round(time.perf_counter() - t0, 1)
    return row


def write_summary(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["error"] = df["error"].fillna("")
    summ = (df.groupby(["system", "metric"])
            .agg(n=("score", "size"), scored=("score", "count"), mean=("score", "mean"), median=("score", "median"),
                 min=("score", "min"), pass_rate=("success", lambda s: s.dropna().astype(float).mean()),
                 errors=("error", lambda e: int((e != "").sum())))
            .round(3).reset_index())
    summ.to_csv(DIR / "deepeval_summary.csv", index=False)
    return summ


def retry_errors(out_csv, gens: dict, golden: dict, judge) -> None:
    df = pd.read_csv(out_csv)
    df["error"] = df["error"].fillna("")
    todo = df[df.error != ""]
    for idx, r in todo.iterrows():
        rec = gens[r.id]
        tc = LLMTestCase(input=rec["query"], actual_output=rec[r.system]["actual_output"],
                         expected_output=golden[r.id]["reference_answer"],
                         retrieval_context=rec[r.system]["retrieval_context"])
        new = measure_one(make_metrics(judge)[r.metric], tc)
        new["retried"] = True
        for k, v in new.items():
            df.loc[idx, k] = v
        print(f"retry {r.id} {r.system} {r.metric}: score={new['score']} {new['error'][:100]}", flush=True)
    df.to_csv(out_csv, index=False)
    print(write_summary(df).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--systems", default="A,C,B")
    parser.add_argument("--ids", default="")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--retry-errors", action="store_true",
                        help="re-score only the rows that errored in deepeval_results.csv and merge them back")
    args = parser.parse_args()
    use_system_certificates()
    gens = json.loads((DIR / "generations.json").read_text(encoding="utf-8"))
    golden = {g["id"]: g for g in json.loads(RAG_GOLDEN.read_text(encoding="utf-8"))}
    judge = OpenAICompatibleJudge()
    out_csv = DIR / "deepeval_results.csv"
    if args.retry_errors:
        retry_errors(out_csv, gens, golden, judge)
        return
    jobs = [(qid, system) for qid, rec in gens.items() if not args.ids or qid in args.ids.split(",")
            for system in args.systems.split(",") if system in rec]
    rows, lock = [], threading.Lock()

    def score_case(qid: str, system: str) -> list[dict]:
        rec = gens[qid]
        tc = LLMTestCase(input=rec["query"], actual_output=rec[system]["actual_output"],
                         expected_output=golden[qid]["reference_answer"],
                         retrieval_context=rec[system]["retrieval_context"])
        out = []
        for name, metric in make_metrics(judge).items():  # fresh metric objects per case (they hold state)
            t0 = time.perf_counter()
            row = {"id": qid, "system": system, "metric": name, "threshold": THRESHOLDS[name]}
            try:
                metric.measure(tc)
                row.update(score=round(float(metric.score), 4), success=bool(metric.success),
                           reason=(metric.reason or "")[:1500], error="")
            except Exception as exc:  # recorded, never hidden
                row.update(score=None, success=None, reason="", error=f"{type(exc).__name__}: {str(exc)[:300]}")
            row["seconds"] = round(time.perf_counter() - t0, 1)
            out.append(row)
            print(f"{qid} {system} {name:26} score={row['score']} {'ERROR ' + row['error'][:80] if row['error'] else ''}",
                  flush=True)
        with lock:
            rows.extend(out)
            pd.DataFrame(rows).to_csv(out_csv, index=False)  # checkpoint
        return out

    # Test cases run in parallel; the judge's rate limiter keeps the account under its request limit.
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(lambda job: score_case(*job), jobs))
    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False)
    summ = (df.groupby(["system", "metric"])
            .agg(n=("score", "size"), scored=("score", "count"), mean=("score", "mean"), median=("score", "median"),
                 min=("score", "min"), pass_rate=("success", lambda s: s.dropna().astype(float).mean()),
                 errors=("error", lambda e: int((e != "").sum())))
            .round(3).reset_index())
    summ.to_csv(DIR / "deepeval_summary.csv", index=False)
    (DIR / "deepeval_judge_usage.json").write_text(json.dumps(judge.usage.summary(), indent=2), encoding="utf-8")
    print(summ.to_string(index=False))
    print("judge usage:", judge.usage.summary())


if __name__ == "__main__":
    main()

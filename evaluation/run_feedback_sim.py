"""Feedback-loop simulation (plan §8.6 "Measure", Phase 9 verify).

Run from the repo root:  python -m evaluation.run_feedback_sim
1. For 10 golden "feedback" queries, run hybrid_rerank (top 10) and vote every returned case relevant / not relevant
   using the same automatic relevance labels as the retrieval evaluation (rel = 1 -> relevant).
2. Re-run all queries with the feedback priors active and compare nDCG@10 before and after.
3. 10 "control" queries (same categories, no votes of their own) check for regressions / transfer.
Votes go to a temporary database, never to artifacts/app.db. No LLM is used.
Caveat: feedback queries are scored on the same queries that were voted on, so their gain is an upper bound;
the control queries are the honest generalization check.
"""
import json
import math
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation.run_retrieval_eval import GOLDEN, build_retriever, relevance
from src.rag.filters import SearchFilters, to_mask, validate
from src.services.feedback_service import RunStore
from src.utils.config import PROJECT_ROOT
from src.utils.net import use_system_certificates

OUT = PROJECT_ROOT / "evaluation" / "results" / "final" / "feedback"
FEEDBACK_IDS = ["G01", "G03", "G05", "G07", "G09", "G11", "G13", "G15", "G17", "G19"]
CONTROL_IDS = ["G02", "G04", "G06", "G08", "G10", "G12", "G14", "G16", "G18", "G20"]


def ndcg(retriever, cases, sym_sets, q) -> tuple[float, list[float], list[str]]:
    filters, _ = validate(SearchFilters(**q["expected_filters"]))
    mask = to_mask(filters, cases)
    exp = q["expected_symptoms"]
    allowed = set(cases.loc[mask, "case_id"])
    n_rel = int((mask & np.all([cases[f"sym_{s}"].to_numpy() for s in exp], axis=0)).sum())
    res = retriever.search(q["query"], filters=filters, top_k=10, mode="hybrid_rerank", category=q["expected_primary"])
    ids = [r["case_id"] for r in res["results"]]
    rels = [relevance(sym_sets[i], exp, i in allowed) for i in ids]
    dcg = sum(r / math.log2(k + 2) for k, r in enumerate(rels))
    idcg = sum(1 / math.log2(k + 2) for k in range(min(10, n_rel)))
    return (dcg / idcg if idcg else 0.0), rels, ids


def main() -> None:
    use_system_certificates()
    retriever, cases = build_retriever()
    sym_cols = [c for c in cases.columns if c.startswith("sym_")]
    sym_sets = {cid: {c[4:] for c in sym_cols if row[c]}
                for cid, row in zip(cases["case_id"], cases[sym_cols].to_dict("records"))}
    golden = {q["id"]: q for q in json.loads(GOLDEN.read_text(encoding="utf-8"))}
    ids = FEEDBACK_IDS + CONTROL_IDS

    before = {qid: ndcg(retriever, cases, sym_sets, golden[qid]) for qid in ids}
    store = RunStore(Path(tempfile.mkdtemp(prefix="feedback_sim_")) / "sim.db")
    votes = 0
    for qid in FEEDBACK_IDS:
        q = golden[qid]
        store.save_run(run_id=qid, endpoint="sim", query=q["query"], request={}, response={}, status="ok",
                       primary_category=q["expected_primary"], priority=None, judge_verdict=None, model="none",
                       prompt_version="", latency_ms=0, tokens_in=0, tokens_out=0)
        _, rels, case_ids = before[qid]
        store.add_feedback(qid, None, None, None, None, [{"case_id": c, "relevant": r == 1.0}
                                                         for c, r in zip(case_ids, rels)])
        votes += len(case_ids)
    retriever.priors_provider = store.priors
    after = {qid: ndcg(retriever, cases, sym_sets, golden[qid]) for qid in ids}

    rows = [{"query_id": qid, "group": "feedback" if qid in FEEDBACK_IDS else "control",
             "category": golden[qid]["expected_primary"], "ndcg_before": round(before[qid][0], 4),
             "ndcg_after": round(after[qid][0], 4), "delta": round(after[qid][0] - before[qid][0], 4),
             "top10_changed": before[qid][2] != after[qid][2]} for qid in ids]
    df = pd.DataFrame(rows)
    summary = {g: {"n": int(len(d)), "ndcg_before": round(d.ndcg_before.mean(), 4),
                   "ndcg_after": round(d.ndcg_after.mean(), 4), "delta_mean": round(d.delta.mean(), 4),
                   "improved": int((d.delta > 1e-9).sum()), "regressed": int((d.delta < -1e-9).sum()),
                   "order_changed": int(d.top10_changed.sum())} for g, d in df.groupby("group")}
    summary["votes"] = votes
    summary["relevant_votes_share"] = round(float(np.mean([r == 1.0 for qid in FEEDBACK_IDS for r in before[qid][1]])), 3)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "feedback_sim_per_query.csv", index=False)
    (OUT / "feedback_sim_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(df.to_string(index=False))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

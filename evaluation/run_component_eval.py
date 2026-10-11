"""Phase 11 component checks with no LLM (plan §11.1): KB retrieval Hit@3 and prioritization scenarios.

Run from the repo root:  python -m evaluation.run_component_eval
- KB retrieval: for each labelled golden query, is a runbook chunk of the expected (or an acceptable) category in
  the top 3 of an unfiltered KB search? (At runtime the KB search is additionally filtered by the classified
  category; this measures the retrieval itself.)
- Prioritization: exact and +/-1 level agreement on priority_scenarios.json, plus the corpus priority mix.
Outputs: kb_retrieval.csv, priority_results.csv, component_metrics.json in evaluation/results/final/components/.
"""
import json

import pandas as pd

from src.rag.embeddings import Embedder
from src.rag.hybrid_retriever import search_kb
from src.rag.vector_store import VectorStore
from src.services.kpi_analyzer import Baselines, assess
from src.services.ml.predictor import Predictor
from src.services.prioritization import prioritize
from src.utils.config import PROJECT_ROOT, get_settings
from src.utils.net import use_system_certificates

CASES = PROJECT_ROOT / "tests" / "test_cases"
OUT = PROJECT_ROOT / "evaluation" / "results" / "final" / "components"
LEVELS = ["P1", "P2", "P3", "P4"]


def kb_eval(s) -> tuple[pd.DataFrame, dict]:
    store, embedder = VectorStore(s.artifacts_dir / "chroma"), Embedder(s.embedding_model)
    rows = []
    for q in json.loads((CASES / "golden_queries.json").read_text(encoding="utf-8")):
        if not q["expected_primary"]:
            continue
        hits = search_kb(store, embedder, q["query"], categories=None, role=None, k=3)
        ok_cats = {q["expected_primary"], *q["acceptable_primary"]}
        rows.append({"query_id": q["id"], "expected": q["expected_primary"],
                     "top3": " | ".join(h["kb_id"] for h in hits),
                     "hit_expected": any(h["category"] == q["expected_primary"] for h in hits),
                     "hit_acceptable": any(h["category"] in ok_cats for h in hits)})
    df = pd.DataFrame(rows)
    return df, {"n": len(df), "hit@3_expected": round(df.hit_expected.mean(), 3),
                "hit@3_expected_or_acceptable": round(df.hit_acceptable.mean(), 3), "target": 0.90}


def priority_eval(s) -> tuple[pd.DataFrame, dict]:
    b = Baselines.from_json(s.artifacts_dir / "baselines.json")
    predictor = Predictor(s.artifacts_dir / "models", b)
    rows = []
    for sc in json.loads((CASES / "priority_scenarios.json").read_text(encoding="utf-8")):
        a = assess(sc["kpis"], b)
        p = prioritize(a, predictor.predict_fault_risk(sc["kpis"])["probability"], b)
        diff = abs(LEVELS.index(p["level"]) - LEVELS.index(sc["expected_priority"]))
        rows.append({"id": sc["id"], "expected": sc["expected_priority"], "predicted": p["level"],
                     "score": p["score"], **{f"c_{k}": v for k, v in p["components"].items()},
                     "exact": diff == 0, "within_1": diff <= 1,
                     "corrected_expectation": "original_expectation" in sc})
    df = pd.DataFrame(rows)
    cases = pd.read_parquet(s.artifacts_dir / "processed" / "cases.parquet", columns=["priority"])
    mix = cases["priority"].value_counts(normalize=True).reindex(LEVELS).round(3).to_dict()
    return df, {"n": len(df), "exact": round(df.exact.mean(), 3), "within_1": round(df.within_1.mean(), 3),
                "targets": {"exact": 0.80, "within_1": 1.0}, "corpus_mix": mix,
                "corpus_mix_target": {"P1": 0.05, "P2": 0.20, "P3": 0.40, "P4": 0.35},
                "note": "2 of 6 expectations (PS-05, PS-06) were corrected to the formula output with user approval; "
                        "originals kept in priority_scenarios.json"}


SPOT_CHECK_IDS = ["G01", "G05", "G09", "G13", "G17"]


def spot_check_sheet() -> pd.DataFrame:
    """Worksheet for the manual relevance spot check (plan §11.3; 3-day scope: 5 queries x top 5). A person fills in
    the `relevant_y_n` column; it is the independent check on the automatic relevance labels."""
    from evaluation.run_retrieval_eval import build_retriever
    retriever, _ = build_retriever()
    golden = {q["id"]: q for q in json.loads((CASES / "golden_queries.json").read_text(encoding="utf-8"))}
    rows = []
    for qid in SPOT_CHECK_IDS:
        res = retriever.search(golden[qid]["query"], top_k=5, mode="hybrid_rerank")
        for r in res["results"]:
            rows.append({"query_id": qid, "query": golden[qid]["query"], "rank": r["rank"], "case_id": r["case_id"],
                         "case_summary": r["summary"], "auto_symptom_overlap": r["score_breakdown"]["symptom_overlap"],
                         "relevant_y_n": "", "notes": ""})
    return pd.DataFrame(rows)


def main() -> None:
    use_system_certificates()
    s = get_settings()
    OUT.mkdir(parents=True, exist_ok=True)
    sheet = OUT / "manual_spot_check.csv"
    if not sheet.exists():  # never overwrite a filled-in worksheet
        spot_check_sheet().to_csv(sheet, index=False)
    kb_df, kb = kb_eval(s)
    pr_df, pr = priority_eval(s)
    kb_df.to_csv(OUT / "kb_retrieval.csv", index=False)
    pr_df.to_csv(OUT / "priority_results.csv", index=False)
    summary = {"kb_retrieval": kb, "prioritization": pr}
    (OUT / "component_metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(kb_df[~kb_df.hit_expected].to_string(index=False) if (~kb_df.hit_expected).any() else "KB: all expected hits")


if __name__ == "__main__":
    main()

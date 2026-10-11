"""Retrieval evaluation and ablation (plan §11.3).

Run from the repo root after bootstrap:  python -m evaluation.run_retrieval_eval [--out DIR]
Relevance of a retrieved case: rel = |expected symptoms in case| / |expected symptoms|, and rel = 0 when an
expected filter is violated. "Relevant" means rel = 1. Expected filters are passed explicitly (as the
UI or classifier would); the rule parser adds query expansion. Limitation: relevance labels come from
the same symptom flags that shape the narratives (circularity, plan R17).
"""
import argparse
import json
import math
import time

import numpy as np
import pandas as pd

from src.rag.embeddings import Embedder
from src.rag.filters import SearchFilters, to_mask, validate
from src.rag.hybrid_retriever import MODES, HybridRetriever
from src.rag.keyword_index import KeywordIndex
from src.rag.vector_store import VectorStore
from src.services.container import case_vectors
from src.utils.config import PROJECT_ROOT, get_settings
from src.utils.net import use_system_certificates

GOLDEN = PROJECT_ROOT / "tests" / "test_cases" / "golden_queries.json"
DEFAULT_OUT = PROJECT_ROOT / "evaluation" / "results" / "final" / "retrieval"
VARIANTS = [(m, True) for m in MODES] + [("hybrid_rerank", False)]


def build_retriever(chroma_only: bool = False) -> tuple[HybridRetriever, pd.DataFrame]:
    s = get_settings()
    cases = pd.read_parquet(s.artifacts_dir / "processed" / "cases.parquet")
    store = VectorStore(s.artifacts_dir / "chroma")
    vectors = None if chroma_only else case_vectors(s.artifacts_dir, s, cases, store)
    if not chroma_only and vectors is None:
        raise RuntimeError("cached case vectors unavailable or misaligned; re-run bootstrap")
    retriever = HybridRetriever(store, KeywordIndex.load(s.artifacts_dir / "bm25"), Embedder(s.embedding_model),
                                cases, s, vectors=vectors)
    return retriever, cases


def relevance(case_syms: set, expected: list[str], compliant: bool) -> float:
    if not compliant:
        return 0.0
    return len(case_syms & set(expected)) / len(expected)


def evaluate(retriever: HybridRetriever, cases: pd.DataFrame, queries: list[dict]) -> pd.DataFrame:
    sym_cols = [c for c in cases.columns if c.startswith("sym_")]
    sym_sets = {cid: {c[4:] for c in sym_cols if row[c]} for cid, row in
                zip(cases["case_id"], cases[sym_cols].to_dict("records"))}
    rows = []
    for q in queries:
        filters, _ = validate(SearchFilters(**q["expected_filters"]))
        mask = to_mask(filters, cases)
        exp = q["expected_symptoms"]
        n_fully_relevant = int((mask & np.all([cases[f"sym_{s}"].to_numpy() for s in exp], axis=0)).sum())
        allowed = set(cases.loc[mask, "case_id"])
        for mode, expansion in VARIANTS:
            t0 = time.perf_counter()
            res = retriever.search(q["query"], filters=filters, top_k=10, mode=mode, use_rule_expansion=expansion)
            latency = (time.perf_counter() - t0) * 1000
            rels = [relevance(sym_sets[r["case_id"]], exp, r["case_id"] in allowed) for r in res["results"]]
            hits = [r == 1.0 for r in rels]
            dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rels))
            idcg = sum(1 / math.log2(i + 2) for i in range(min(10, n_fully_relevant)))
            first = next((i + 1 for i, h in enumerate(hits) if h), None)
            rows.append({"query_id": q["id"], "mode": mode + ("" if expansion else "_no_expansion"),
                         "hit@5": float(any(hits[:5])), "p@5": float(np.mean(hits[:5])) if hits else 0.0,
                         "mrr@10": 1 / first if first else 0.0, "ndcg@10": dcg / idcg if idcg else 0.0,
                         "filter_compliance": float(np.mean([r["case_id"] in allowed for r in res["results"]]))
                         if res["results"] else 1.0,
                         "n_results": len(res["results"]), "n_fully_relevant_in_corpus": n_fully_relevant,
                         "latency_ms": round(latency, 1)})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--chroma-only", action="store_true", help="filtered dense via Chroma where (pre-fix path)")
    args = parser.parse_args()
    use_system_certificates()
    out = __import__("pathlib").Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    queries = [q for q in json.loads(GOLDEN.read_text(encoding="utf-8")) if q["in_scope"] and q["expected_symptoms"]]
    retriever, cases = build_retriever(args.chroma_only)
    retriever.search("warm up", top_k=1)  # load model weights and caches before timing
    per_query = evaluate(retriever, cases, queries)
    per_query.to_csv(out / "retrieval_per_query.csv", index=False)
    summary = per_query.groupby("mode").agg(**{
        "hit@5": ("hit@5", "mean"), "p@5": ("p@5", "mean"), "mrr@10": ("mrr@10", "mean"),
        "ndcg@10": ("ndcg@10", "mean"), "filter_compliance": ("filter_compliance", "mean"),
        "latency_p50_ms": ("latency_ms", "median"), "latency_p95_ms": ("latency_ms", lambda s: s.quantile(0.95)),
    }).round(4)
    order = ["bm25", "dense", "hybrid", "hybrid_rerank", "hybrid_rerank_no_expansion"]
    summary = summary.reindex([m for m in order if m in summary.index])
    summary.to_csv(out / "retrieval_metrics.csv")
    (out / "run_info.json").write_text(json.dumps({"queries": len(queries), "top_k": 10,
                                                   "relevance": "graded symptom overlap; filters must hold",
                                                   "filtered_dense": "chroma_where" if args.chroma_only
                                                   else "exact_cached_vectors"}, indent=2))
    print(f"{len(queries)} queries\n{summary.to_string()}")


if __name__ == "__main__":
    main()

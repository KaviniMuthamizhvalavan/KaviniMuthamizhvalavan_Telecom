"""Hybrid retrieval: dense (Chroma) + BM25 under one metadata filter, RRF fusion, symptom/feedback rerank.

Plan §7.6-7.7. Modes: "bm25", "dense", "hybrid" (RRF), "hybrid_rerank" (default).
Filtered dense search: when the cached case vectors are supplied and a filter narrows the corpus, the
matching rows are scored exactly (dot product of normalized vectors = cosine) instead of a Chroma `where`
query, which is slow on 100k records. Unfiltered queries still use the Chroma HNSW index.
`symptom_overlap` (Jaccard of query symptoms vs case symptoms) is reported in every mode
(approved contract clarification M1); it only changes the ranking in hybrid_rerank.
"""
import time
from collections.abc import Callable

import numpy as np
import pandas as pd

from src.rag.documents import anomalies, build_case_summary
from src.rag.embeddings import Embedder
from src.rag.filters import SearchFilters, to_chroma_where, to_mask, validate
from src.rag.keyword_index import KeywordIndex
from src.rag.vector_store import CASES, VectorStore
from src.services import query_parser
from src.utils.schema import SYMPTOMS

MODES = ("bm25", "dense", "hybrid", "hybrid_rerank")
PriorsProvider = Callable[[str | None], dict[str, float]]  # category -> {case_id: prior in [0, 1]}


class HybridRetriever:
    def __init__(self, store: VectorStore, keyword_index: KeywordIndex, embedder: Embedder, cases: pd.DataFrame,
                 settings, priors_provider: PriorsProvider | None = None, vectors: np.ndarray | None = None):
        if list(cases["case_id"]) != keyword_index.ids:
            raise ValueError("case order differs between cases.parquet and the BM25 index; re-run bootstrap")
        if vectors is not None and len(vectors) != len(cases):
            raise ValueError("cached case vectors do not match cases.parquet; re-run bootstrap")
        self.vectors = vectors  # row i = embedding of cases.iloc[i]; None -> Chroma for every dense query
        self.store, self.kindex, self.embedder, self.cases, self.s = store, keyword_index, embedder, cases, settings
        self.priors_provider = priors_provider
        self._sym_matrix = cases[[f"sym_{c}" for c in SYMPTOMS]].to_numpy(dtype=bool)
        self._pos = {cid: i for i, cid in enumerate(cases["case_id"])}

    # ------------------------------------------------------------------ public
    def search(self, query: str, filters: SearchFilters | None = None, top_k: int | None = None,
               mode: str = "hybrid_rerank", use_rule_expansion: bool = True,
               query_symptoms: list[str] | None = None, category: str | None = None) -> dict:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        t0 = time.perf_counter()
        top_k = top_k or self.s.top_k
        parsed = query_parser.parse(query) if use_rule_expansion else query_parser.RuleParse()
        symptoms = list(query_symptoms) if query_symptoms is not None else parsed.symptoms

        explicit = filters or SearchFilters()
        merged = explicit.model_dump()
        for key, values in parsed.filters.items():  # explicit filters win, field by field
            if not merged.get(key):
                merged[key] = values
        applied, warnings = validate(SearchFilters(**merged))
        mask = to_mask(applied, self.cases)
        total = int(mask.sum())

        expansion = [SYMPTOMS[c].label for c in symptoms if SYMPTOMS[c].label not in query.lower()]
        text = " ".join([query, *expansion]).strip()
        n_cand = min(self.s.candidate_k, total)
        timings = {}

        dense_rank: dict[int, int] = {}
        if mode != "bm25" and n_cand:
            t = time.perf_counter()
            q = self.embedder.embed_query(text)
            if self.vectors is not None and total < len(self.cases):
                dense_rank = self._dense_masked(q, mask, n_cand)
            else:
                hits = self.store.query(CASES, q, n_cand, to_chroma_where(applied))
                dense_rank = {self._pos[cid]: r for r, (cid, _, _) in enumerate(hits, start=1)}
            timings["dense"] = round((time.perf_counter() - t) * 1000, 1)

        sparse_rank: dict[int, int] = {}
        if mode != "dense" and n_cand:
            t = time.perf_counter()
            scores = np.where(mask, self.kindex.scores(text), -np.inf)
            top = np.argpartition(-scores, n_cand - 1)[:n_cand]
            top = top[np.argsort(-scores[top])]
            top = top[np.isfinite(scores[top]) & (scores[top] > 0)]
            sparse_rank = {int(i): r for r, i in enumerate(top, start=1)}
            timings["sparse"] = round((time.perf_counter() - t) * 1000, 1)

        t = time.perf_counter()
        k = self.s.rrf_k
        candidates = set(dense_rank) | set(sparse_rank)
        rrf = {i: self.s.w_dense * (1 / (k + dense_rank[i]) if i in dense_rank else 0)
               + self.s.w_sparse * (1 / (k + sparse_rank[i]) if i in sparse_rank else 0) for i in candidates}
        overlap = self._overlap(np.fromiter(candidates, dtype=int), symptoms)
        priors = self.priors_provider(category) if (self.priors_provider and mode == "hybrid_rerank") else {}
        if rrf:
            lo, hi = min(rrf.values()), max(rrf.values())
            norm = {i: (v - lo) / (hi - lo) if hi > lo else 1.0 for i, v in rrf.items()}
        final = {}
        for i in candidates:
            prior = priors.get(self.cases.iat[i, 0], 0.5)
            final[i] = (norm[i] + self.s.rerank_symptom_weight * overlap[i]
                        + self.s.rerank_feedback_weight * (prior - 0.5)) if mode == "hybrid_rerank" else rrf[i]
        ranked = sorted(candidates, key=lambda i: (-final[i], i))[:top_k]
        timings["rerank"] = round((time.perf_counter() - t) * 1000, 1)

        results = []
        for r, i in enumerate(ranked, start=1):
            row = self.cases.iloc[i]
            results.append({
                "rank": r, "case_id": row["case_id"], "final_score": round(float(final[i]), 4),
                "score_breakdown": {"dense_rank": dense_rank.get(i), "bm25_rank": sparse_rank.get(i),
                                    "rrf": round(float(rrf[i]), 5), "symptom_overlap": round(float(overlap[i]), 3),
                                    "feedback_prior": round(float(priors.get(row["case_id"], 0.5)), 3)},
                "state": row["state"], "city": row["city"], "season": row["season"], "weather": row["weather"],
                "primary_category": row["primary_category"],
                "secondary_categories": [c for c in (row["secondary_1"], row["secondary_2"]) if c],
                "priority": row["priority"], "fault_risk_band": row["fault_risk_band"],
                "anomalies": anomalies(row), "summary": build_case_summary(row),
            })
        if total < top_k:
            warnings.append(f"Only {total} records match these filters.")
        if not symptoms:
            warnings.append("No network symptoms were recognized in the query; ranking uses text similarity only.")
        timings["total"] = round((time.perf_counter() - t0) * 1000, 1)
        return {"query": query, "mode": mode, "parsed": {"symptoms": parsed.symptoms, "filters": parsed.filters},
                "applied_filters": applied.model_dump(exclude_none=True), "expansion_terms": expansion,
                "query_symptoms": symptoms, "total_candidates": total, "results": results,
                "warnings": warnings, "timings_ms": timings}

    # ------------------------------------------------------------------ helpers
    def _dense_masked(self, q: np.ndarray, mask: np.ndarray, n: int) -> dict[int, int]:
        """Exact top-n cosine over the rows allowed by the filter mask (ties broken by row position)."""
        idx = np.flatnonzero(mask)
        sims = self.vectors[idx] @ q.astype(self.vectors.dtype)
        top = np.argpartition(-sims, n - 1)[:n] if n < len(idx) else np.arange(len(idx))
        top = top[np.lexsort((idx[top], -sims[top]))]
        return {int(idx[j]): r for r, j in enumerate(top, start=1)}

    def _overlap(self, idx: np.ndarray, symptoms: list[str]) -> dict[int, float]:
        if not len(idx):
            return {}
        if not symptoms:
            return {int(i): 0.0 for i in idx}
        q = np.array([c in symptoms for c in SYMPTOMS])
        m = self._sym_matrix[idx]
        inter = (m & q).sum(axis=1)
        union = (m | q).sum(axis=1)
        return {int(i): float(v) for i, v in zip(idx, np.where(union > 0, inter / np.maximum(union, 1), 0.0))}


ROLE_SECTIONS = {
    "analyst": ["kpi-signature", "likely-root-causes"],
    "recommender": ["diagnostic-checks", "corrective-actions", "escalation-criteria"],
    "basic": ["likely-root-causes", "corrective-actions", "diagnostic-checks"],  # /recommend single pass
}


def search_kb(store: VectorStore, embedder: Embedder, query: str, categories: list[str] | None = None,
              role: str | None = None, k: int = 4) -> list[dict]:
    """Dense KB retrieval filtered to the incident categories and the role's sections (plan §7.6 step 9).

    Falls back to no section filter when fewer than 2 chunks match.
    """
    from src.rag.vector_store import KB

    def run(sections):
        clauses = []
        if categories:
            clauses.append({"category": {"$in": list(categories)}})
        if sections:
            clauses.append({"section": {"$in": sections}})
        where = None if not clauses else (clauses[0] if len(clauses) == 1 else {"$and": clauses})
        res = store.collection(KB).query(query_embeddings=[embedder.embed_query(query).tolist()], n_results=k,
                                         where=where, include=["distances", "metadatas", "documents"])
        return [{"kb_id": i, "score": round(1 - d, 4), "category": m["category"], "section": m["section"],
                 "title": m["title"], "text": doc}
                for i, d, m, doc in zip(res["ids"][0], res["distances"][0], res["metadatas"][0], res["documents"][0])]

    hits = run(ROLE_SECTIONS.get(role))
    if len(hits) < 2 and role:
        hits = run(None)
    return hits

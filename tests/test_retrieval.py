"""Filters and hybrid retrieval on a small temporary index (400 real cases)."""
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.rag.documents import build_documents
from src.rag.filters import InvalidFilterError, KPIRange, SearchFilters, to_chroma_where, to_mask, validate
from src.rag.hybrid_retriever import HybridRetriever
from src.rag.keyword_index import KeywordIndex
from src.rag.vector_store import CASES, VectorStore
from src.utils.config import get_settings

ART = get_settings().artifacts_dir


FILTER_CASES = [
    SearchFilters(state=["TX", "CA"]),
    SearchFilters(season=["winter"], weather=["Rain"]),
    SearchFilters(symptoms=["high_latency", "high_packet_loss"]),
    SearchFilters(categories=["TRANSPORT_QOS"], priority=["P1", "P2"]),
    SearchFilters(kpi_ranges={"latency_ms": KPIRange(min=100), "user_count": KPIRange(max=5000)}),
    SearchFilters(state=["Texas"], season=["Fall", "Winter"], symptoms=["low_throughput"]),
]


@pytest.mark.parametrize("f", FILTER_CASES)
def test_chroma_where_and_mask_select_identical_records(small_index, f):
    _, store, cases = small_index
    f, _ = validate(f)
    mask_ids = set(cases.loc[to_mask(f, cases), "case_id"])
    got = store.collection(CASES).get(where=to_chroma_where(f), include=[])["ids"]
    assert set(got) == mask_ids


def test_validate_normalizes_and_rejects():
    f, warn = validate(SearchFilters(state=["texas", "NY"], season=["autumn"], city="  New Michael "))
    assert f.state == ["NY", "TX"] and f.season == ["Fall"] and f.city == "new michael" and warn
    with pytest.raises(InvalidFilterError):
        validate(SearchFilters(state=["ZZ"]))
    with pytest.raises(InvalidFilterError):
        validate(SearchFilters(symptoms=["slow_vibes"]))


@pytest.mark.parametrize("mode", ["bm25", "dense", "hybrid", "hybrid_rerank"])
def test_search_respects_filters_in_every_mode(small_index, mode):
    retriever, _, cases = small_index
    res = retriever.search("high latency and packet loss", filters=SearchFilters(season=["Winter"]), mode=mode)
    seasons = set(cases.set_index("case_id").loc[[r["case_id"] for r in res["results"]], "season"])
    assert res["results"] and seasons == {"Winter"}
    assert res["applied_filters"]["season"] == ["Winter"]


def test_rerank_prefers_full_symptom_matches(small_index):
    retriever, _, _ = small_index
    res = retriever.search("high latency and packet loss", mode="hybrid_rerank", top_k=5)
    assert res["parsed"]["symptoms"] == ["high_latency", "high_packet_loss"]
    top = res["results"][0]
    assert top["score_breakdown"]["symptom_overlap"] > 0
    assert {"dense_rank", "bm25_rank", "rrf", "symptom_overlap", "feedback_prior"} <= set(top["score_breakdown"])


def test_query_filters_extracted_and_explicit_wins(small_index):
    retriever, _, _ = small_index
    res = retriever.search("packet loss in Texas during winter", filters=SearchFilters(season=["Summer"]))
    assert res["applied_filters"]["state"] == ["TX"] and res["applied_filters"]["season"] == ["Summer"]


def test_impossible_filter_returns_empty_with_warning(small_index):
    retriever, _, _ = small_index
    res = retriever.search("packet loss", filters=SearchFilters(city="no such city"))
    assert res["results"] == [] and res["total_candidates"] == 0 and res["warnings"]


def test_feedback_prior_changes_rank(small_index):
    retriever, _, _ = small_index
    base = retriever.search("high latency and packet loss", top_k=5)
    target = base["results"][1]["case_id"]
    retriever.priors_provider = lambda category: {target: 1.0}
    boosted = retriever.search("high latency and packet loss", top_k=5)
    retriever.priors_provider = None
    rank = lambda r: [x["case_id"] for x in r["results"]].index(target) if target in [x["case_id"] for x in r["results"]] else 99  # noqa: E731
    assert rank(boosted) <= rank(base)
    assert np.isclose([x for x in boosted["results"] if x["case_id"] == target][0]["score_breakdown"]["feedback_prior"], 1.0)


@pytest.mark.parametrize("f", FILTER_CASES[:4])
def test_exact_filtered_dense_matches_chroma_where(small_index, f):
    """The cached-vector path for filtered queries returns the same dense ranking as a Chroma `where` query."""
    fast, store, cases = small_index
    chroma = HybridRetriever(store, fast.kindex, fast.embedder, cases, fast.s)  # no vectors -> Chroma path
    for q in ("high latency and packet loss", "low throughput during snow"):
        a = fast.search(q, filters=f, mode="dense", top_k=10, use_rule_expansion=False)
        b = chroma.search(q, filters=f, mode="dense", top_k=10, use_rule_expansion=False)
        assert [r["case_id"] for r in a["results"]] == [r["case_id"] for r in b["results"]]
        assert a["total_candidates"] == b["total_candidates"]


def test_retriever_rejects_misaligned_vectors(small_index):
    r, store, cases = small_index
    with pytest.raises(ValueError):
        HybridRetriever(store, r.kindex, r.embedder, cases, r.s, vectors=r.vectors[:-1])

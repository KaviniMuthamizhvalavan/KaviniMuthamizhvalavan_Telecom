import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from src.rag.data_loader import SAMPLE_PATH, load_raw
from src.rag.preprocessing import normalize
from src.services.kpi_analyzer import compute_baselines


@pytest.fixture(scope="session")
def sample_cases() -> pd.DataFrame:
    """Normalized committed sample (about 10k rows)."""
    if not SAMPLE_PATH.exists():
        pytest.skip("sample CSV missing; run python -m scripts.make_sample")
    return normalize(load_raw("sample"))


@pytest.fixture(scope="session")
def sample_baselines(sample_cases):
    return compute_baselines(sample_cases, "test")


ART = __import__("src.utils.config", fromlist=["get_settings"]).get_settings().artifacts_dir


@pytest.fixture(scope="session")
def small_index():
    path = ART / "processed" / "cases.parquet"
    if not path.exists():
        pytest.skip("cases.parquet missing; run bootstrap")
    cases = pd.read_parquet(path)
    if "priority" not in cases:
        pytest.skip("cases not prioritized yet")
    cases = cases.iloc[:400].reset_index(drop=True)
    from src.rag.documents import build_documents
    from src.rag.embeddings import Embedder
    from src.rag.hybrid_retriever import HybridRetriever
    from src.rag.keyword_index import KeywordIndex
    from src.rag.vector_store import CASES, VectorStore
    from src.utils.config import get_settings
    embedder = Embedder(get_settings().embedding_model)
    ids, texts, metas = build_documents(cases)
    tmp = Path(tempfile.mkdtemp(prefix="retrieval_test_"))
    store = VectorStore(tmp / "chroma")
    vectors = embedder.embed_documents(texts)
    store.upsert(CASES, ids, vectors, metas, texts)
    from src.rag.ingest import index_kb
    index_kb(store, embedder)
    kindex = KeywordIndex.build(texts, ids)
    settings = SimpleNamespace(top_k=5, candidate_k=50, rrf_k=60, w_dense=1.0, w_sparse=1.0,
                               rerank_symptom_weight=0.3, rerank_feedback_weight=0.1)
    yield HybridRetriever(store, kindex, embedder, cases, settings, vectors=vectors), store, cases
    del store
    shutil.rmtree(tmp, ignore_errors=True)



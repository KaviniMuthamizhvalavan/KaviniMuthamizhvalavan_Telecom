"""Service container: builds every runtime singleton once at API startup, fail-soft (plan §6.2, Phase 7).

If artifacts are missing, the app still starts; `ready` is False and `missing` lists what to build.
The embedding model loads here, at startup, so the first query is not slow (approved clarification M5).
"""
import logging
from dataclasses import dataclass, field

import pandas as pd

from src.utils.config import Settings

log = logging.getLogger(__name__)


@dataclass
class ServiceContainer:
    settings: Settings
    baselines: object = None
    cases: pd.DataFrame | None = None
    predictor: object = None
    embedder: object = None
    store: object = None
    retriever: object = None
    guardrails: object = None
    llm: object = None
    judge_llm: object = None  # None -> the runtime LLM judges (JUDGE_LLM_MODEL empty)
    runs: object = None
    graph: object = None  # compiled lazily on the first /troubleshoot
    case_index: dict = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return not self.missing

    @classmethod
    def build(cls, settings: Settings) -> "ServiceContainer":
        c = cls(settings)
        art = settings.artifacts_dir

        def step(name, fn):
            try:
                return fn()
            except Exception as exc:  # fail-soft: record and continue
                c.missing.append(name)
                c.errors[name] = f"{type(exc).__name__}: {exc}"
                log.warning("startup: %s unavailable (%s)", name, exc)
                return None

        from src.rag.embeddings import Embedder
        from src.rag.hybrid_retriever import HybridRetriever
        from src.rag.keyword_index import KeywordIndex
        from src.rag.vector_store import CASES, VectorStore
        from src.services.kpi_analyzer import Baselines
        from src.services.ml.predictor import Predictor

        c.baselines = step("baselines", lambda: Baselines.from_json(art / "baselines.json"))
        c.cases = step("cases", lambda: _load_cases(art))
        if c.cases is not None:
            c.case_index = {cid: i for i, cid in enumerate(c.cases["case_id"])}
        if c.baselines is not None:
            c.predictor = step("models", lambda: Predictor(art / "models", c.baselines))
        c.embedder = step("embedding_model", lambda: Embedder(settings.embedding_model))

        def open_store():
            store = VectorStore(art / "chroma")
            if store.count(CASES) == 0:
                raise RuntimeError("netops_cases collection is empty")
            return store

        c.store = step("vector_store", open_store)
        kindex = step("keyword_index", lambda: KeywordIndex.load(art / "bm25"))
        if all(x is not None for x in (c.store, kindex, c.embedder, c.cases)):
            vectors = case_vectors(art, settings, c.cases, c.store)
            c.retriever = step("retriever", lambda: HybridRetriever(c.store, kindex, c.embedder, c.cases, settings,
                                                                    vectors=vectors))
        if c.embedder is not None:
            from src.services.guardrails import Guardrails
            c.guardrails = step("guardrails", lambda: Guardrails(c.embedder))
        c.llm = build_llm(settings)
        if settings.judge_llm_model and c.llm.configured:
            from src.services.llm_client import LLMClient
            c.judge_llm = LLMClient(settings, cache_path=art / "llm_cache.db", model=settings.judge_llm_model,
                                    limiter=c.llm.limiter, circuit=c.llm.circuit)
        from src.services.feedback_service import RunStore
        try:  # optional: persistence failures never block readiness
            c.runs = RunStore(art / "app.db")
            if c.retriever is not None:  # feedback priors feed the rerank (plan §8.6)
                c.retriever.priors_provider = c.runs.priors
        except Exception as exc:
            c.errors["database"] = f"{type(exc).__name__}: {exc}"
            log.warning("startup: run store unavailable (%s)", exc)
        return c


def build_llm(settings: Settings):
    """LLM client; never fails startup. Without a key it reports unavailable and requests run in reduced mode."""
    from src.services.llm_client import LLMClient
    return LLMClient(settings, cache_path=settings.artifacts_dir / "llm_cache.db")


def case_vectors(art, settings: Settings, cases: pd.DataFrame, store):
    """Cached case vectors for the exact filtered dense path, spot-checked against Chroma.

    Optional: on any problem the retriever falls back to Chroma `where` queries (slower, same design).
    """
    import numpy as np

    from src.rag.ingest import load_case_vectors
    from src.rag.vector_store import CASES
    try:
        vectors = load_case_vectors(art, settings.embedding_model, len(cases))
        if vectors is None:
            log.warning("startup: no cached case vectors; filtered dense search uses Chroma")
            return None
        pos = np.linspace(0, len(cases) - 1, 8).astype(int)
        stored = store.collection(CASES).get(ids=list(cases["case_id"].iloc[pos]), include=["embeddings"])
        by_id = dict(zip(stored["ids"], stored["embeddings"]))
        if not all(np.allclose(vectors[i], by_id[cases["case_id"].iat[i]], atol=1e-5) for i in pos):
            log.warning("startup: cached case vectors differ from Chroma; filtered dense search uses Chroma")
            return None
        return vectors
    except Exception as exc:
        log.warning("startup: case vectors unavailable (%s); filtered dense search uses Chroma", exc)
        return None


def _load_cases(art) -> pd.DataFrame:
    cases = pd.read_parquet(art / "processed" / "cases.parquet")
    if "priority" not in cases:
        raise RuntimeError("cases are not prioritized; run python -m scripts.bootstrap")
    return cases

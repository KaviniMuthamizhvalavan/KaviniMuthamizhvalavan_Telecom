"""Index labelled cases (and KB chunks when present) into Chroma + BM25 (plan Phase 5, §7.1).

Requires artifacts/processed/cases.parquet with priority (Phases 1, 3, 4). Embeddings are cached in
artifacts/embeddings/ keyed by dataset hash, narrative template version and model, so a re-index
after a metadata change does not re-embed.
"""
import json
import logging
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.rag.documents import TEMPLATE_VERSION, build_documents
from src.rag.embeddings import Embedder
from src.rag.keyword_index import KeywordIndex
from src.rag.vector_store import CASES, VectorStore
from src.services.kpi_analyzer import Baselines
from src.utils.config import get_settings

log = logging.getLogger(__name__)


def _cache_key(b: Baselines, model: str, n: int) -> str:
    return f"{b.dataset_sha256[:16]}_{TEMPLATE_VERSION}_{model.replace('/', '_')}_{n}"


def load_case_vectors(art, model: str, n: int) -> np.ndarray | None:
    """Cached case embeddings in cases.parquet row order, or None when the cache is absent."""
    path = art / "embeddings" / f"{_cache_key(Baselines.from_json(art / 'baselines.json'), model, n)}.npy"
    return np.load(path) if path.exists() else None


def ingest_cases(embedder: Embedder | None = None, rebuild: bool = False) -> dict:
    s = get_settings()
    art = s.artifacts_dir
    cases = pd.read_parquet(art / "processed" / "cases.parquet")
    if "priority" not in cases:
        raise RuntimeError("cases.parquet has no priority; run python -m src.services.prioritization first")
    b = Baselines.from_json(art / "baselines.json")
    t0 = time.perf_counter()
    ids, texts, metas = build_documents(cases)
    t_docs = time.perf_counter() - t0

    cache = art / "embeddings" / f"{_cache_key(b, s.embedding_model, len(ids))}.npy"
    t1 = time.perf_counter()
    if cache.exists() and not rebuild:
        vectors = np.load(cache)
        log.info("loaded cached embeddings %s", cache.name)
    else:
        embedder = embedder or Embedder(s.embedding_model)
        log.info("embedding %d narratives with %s ...", len(texts), s.embedding_model)
        vectors = embedder.embed_documents(texts, batch_size=64, show_progress=True)
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.save(cache, vectors)
    t_embed = time.perf_counter() - t1

    t2 = time.perf_counter()
    store = VectorStore(art / "chroma")
    store.reset(CASES)

    def progress(done, total):
        if done % 20_000 < store.max_batch or done == total:
            log.info("chroma upsert %d/%d", done, total)

    store.upsert(CASES, ids, vectors, metas, texts, progress=progress)
    t_chroma = time.perf_counter() - t2

    t3 = time.perf_counter()
    KeywordIndex.build(texts, ids).save(art / "bm25")
    t_bm25 = time.perf_counter() - t3

    info = {"cases": len(ids), "chroma_count": store.count(CASES), "embedding_model": s.embedding_model,
            "embedding_dim": int(vectors.shape[1]), "template_version": TEMPLATE_VERSION,
            "dataset_sha256": b.dataset_sha256, "data_source": s.data_source,
            "timings_s": {"documents": round(t_docs, 1), "embeddings": round(t_embed, 1),
                          "chroma": round(t_chroma, 1), "bm25": round(t_bm25, 1)}}
    _update_manifest("cases", info)
    return info


def _update_manifest(section: str, info: dict) -> None:
    path = get_settings().artifacts_dir / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    manifest[section] = {**info, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def ingest_kb(embedder: Embedder | None = None) -> dict:
    """Chunk and index the KB runbooks into the `netops_kb` collection (small: about 80 chunks)."""
    from src.rag.vector_store import KB

    s = get_settings()
    store = VectorStore(s.artifacts_dir / "chroma")
    chunks = index_kb(store, embedder or Embedder(s.embedding_model))
    info = {"chunks": len(chunks), "chroma_count": store.count(KB),
            "categories": sorted({c.category for c in chunks})}
    _update_manifest("kb", info)
    return info


def index_kb(store: VectorStore, embedder: Embedder) -> list:
    """(Re)build the KB collection in `store` from the runbooks; returns the chunks."""
    from src.rag.chunking import chunk_all
    from src.rag.vector_store import KB

    chunks = chunk_all()
    vectors = embedder.embed_documents([c.text for c in chunks])
    store.reset(KB)
    metas = [{"category": c.category, "section": c.section, "title": c.title, "doc_version": c.doc_version}
             for c in chunks]
    store.upsert(KB, [c.kb_id for c in chunks], vectors, metas, [c.text for c in chunks])
    return chunks


def main() -> None:
    import argparse

    from src.utils.net import use_system_certificates

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    use_system_certificates()
    parser = argparse.ArgumentParser(description="Index cases and/or the KB")
    parser.add_argument("--only", choices=["cases", "kb"], default=None)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    if args.only in (None, "cases"):
        print(ingest_cases(rebuild=args.rebuild))
    if args.only in (None, "kb"):
        print(ingest_kb())


if __name__ == "__main__":
    main()

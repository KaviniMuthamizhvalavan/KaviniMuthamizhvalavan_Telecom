"""Embedder loading (backend investigation 2026-10-07): a cached model must load without network access."""
import sentence_transformers

from src.rag.embeddings import Embedder


class _FakeST:
    calls: list = []

    def __init__(self, name, device="cpu", local_files_only=False):
        _FakeST.calls.append(local_files_only)
        if local_files_only and name == "not-cached":
            raise OSError("not in local cache")

    def get_embedding_dimension(self):
        return 384


def test_cached_model_loads_offline_first(monkeypatch):
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", _FakeST)
    _FakeST.calls = []
    Embedder("BAAI/bge-small-en-v1.5")
    assert _FakeST.calls == [True]  # no online attempt when the cache has the model


def test_uncached_model_falls_back_to_download(monkeypatch):
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", _FakeST)
    _FakeST.calls = []
    Embedder("not-cached")
    assert _FakeST.calls == [True, False]

"""BM25 keyword index (bm25s + English stemming) returning full score vectors (plan §7.6).

Scores are aligned with the case order used at build time, so a boolean metadata mask can be
applied directly before taking the top candidates.
"""
import json
from pathlib import Path

import bm25s
import numpy as np
import Stemmer

_STEMMER = Stemmer.Stemmer("english")


def tokenize(texts: list[str], return_ids: bool = True):
    return bm25s.tokenize(texts, stopwords="en", stemmer=_STEMMER, show_progress=False, return_ids=return_ids)


class KeywordIndex:
    def __init__(self, retriever: bm25s.BM25, ids: list[str]):
        self.retriever = retriever
        self.ids = ids
        self.vocab = set(retriever.vocab_dict) if getattr(retriever, "vocab_dict", None) else None

    @classmethod
    def build(cls, texts: list[str], ids: list[str]) -> "KeywordIndex":
        retriever = bm25s.BM25()
        retriever.index(tokenize(texts), show_progress=False)
        return cls(retriever, ids)

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.retriever.save(str(directory))
        (directory / "case_ids.json").write_text(json.dumps(self.ids), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> "KeywordIndex":
        retriever = bm25s.BM25.load(str(directory))
        ids = json.loads((directory / "case_ids.json").read_text(encoding="utf-8"))
        return cls(retriever, ids)

    def scores(self, query: str) -> np.ndarray:
        tokens = tokenize([query], return_ids=False)[0]
        if self.vocab is not None:
            tokens = [t for t in tokens if t in self.vocab]
        if not tokens:
            return np.zeros(len(self.ids), dtype=np.float32)
        return np.asarray(self.retriever.get_scores(tokens), dtype=np.float32)

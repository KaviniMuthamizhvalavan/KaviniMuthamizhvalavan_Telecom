"""ChromaDB persistent store with two collections: historical cases and KB runbook chunks (plan §7.5)."""
from pathlib import Path

import chromadb
import numpy as np

CASES = "netops_cases"
KB = "netops_kb"


class VectorStore:
    def __init__(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(path), settings=chromadb.Settings(anonymized_telemetry=False))
        self.max_batch = self.client.get_max_batch_size()

    def collection(self, name: str):
        return self.client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"})

    def reset(self, name: str) -> None:
        if name in [c.name for c in self.client.list_collections()]:
            self.client.delete_collection(name)

    def upsert(self, name: str, ids: list[str], embeddings: np.ndarray, metadatas: list[dict],
               documents: list[str], progress=None) -> None:
        coll = self.collection(name)
        for start in range(0, len(ids), self.max_batch):
            end = start + self.max_batch
            coll.upsert(ids=ids[start:end], embeddings=embeddings[start:end].tolist(),
                        metadatas=metadatas[start:end], documents=documents[start:end])
            if progress:
                progress(min(end, len(ids)), len(ids))

    def query(self, name: str, embedding: np.ndarray, n: int, where: dict | None = None) -> list[tuple[str, float, dict]]:
        """Returns (id, cosine distance, metadata) best first. n is capped by the caller to the match count."""
        if n <= 0:
            return []
        res = self.collection(name).query(query_embeddings=[embedding.tolist()], n_results=n, where=where,
                                          include=["distances", "metadatas"])
        return list(zip(res["ids"][0], res["distances"][0], res["metadatas"][0]))

    def get(self, name: str, ids: list[str]) -> dict:
        return self.collection(name).get(ids=ids, include=["metadatas", "documents"])

    def count(self, name: str) -> int:
        return self.collection(name).count()

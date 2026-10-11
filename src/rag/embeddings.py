"""Dense embeddings with a local sentence-transformers model (plan §7.4).

The model loads in __init__, so constructing the Embedder at API startup avoids a slow first
query (approved contract clarification M5).
"""
import logging

import numpy as np

log = logging.getLogger(__name__)
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder:
    def __init__(self, model_name: str, device: str = "cpu", query_prefix: bool = True):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        try:
            # Cached model: load without contacting the Hub. Otherwise the HF client re-checks every model file
            # online and, with no network, retries each request with back-off (measured: 2 min startup offline).
            self.model = SentenceTransformer(model_name, device=device, local_files_only=True)
        except OSError:
            log.info("embedding model %s not in the local cache; downloading it", model_name)
            self.model = SentenceTransformer(model_name, device=device)
        self.query_prefix = BGE_QUERY_PREFIX if (query_prefix and "bge" in model_name.lower()) else ""
        self.dim = self.model.get_embedding_dimension()

    def embed_documents(self, texts: list[str], batch_size: int = 64, show_progress: bool = False) -> np.ndarray:
        return self.model.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                                 show_progress_bar=show_progress, convert_to_numpy=True).astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self.model.encode([self.query_prefix + text], normalize_embeddings=True, show_progress_bar=False,
                                 convert_to_numpy=True)[0].astype(np.float32)

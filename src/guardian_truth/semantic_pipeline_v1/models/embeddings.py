"""BGE-M3 recall adapter. Similarity is candidate evidence, never proof."""

from __future__ import annotations


class BGEEmbedder:
    def __init__(self, model_name: str, model, cache=None):
        self.model_name, self.model = model_name, model
        self.cache = cache

    @staticmethod
    def load(model_name: str, device: str):
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(model_name, device=device)

    def similarity(self, query: str, documents: list[str]) -> list[float]:
        from ..cache import content_key
        key = content_key(stage="embedding", model=self.model_name,
                          config={"normalize_embeddings": True},
                          payload={"query": query, "documents": documents})
        cached = self.cache.get("embedding", key) if self.cache else None
        if cached is not None:
            return [float(value) for value in cached["scores"]]
        import numpy as np
        vectors = self.model.encode([query, *documents], normalize_embeddings=True,
                                    convert_to_numpy=True)
        result = [float(value) for value in np.dot(vectors[1:], vectors[0])]
        if self.cache:
            self.cache.put("embedding", key, {"scores": result})
        return result

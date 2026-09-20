"""BGE pairwise reranker adapter."""

from __future__ import annotations


class BGEReranker:
    def __init__(self, model_name: str, model, cache=None):
        self.model_name, self.model = model_name, model
        self.cache = cache

    @staticmethod
    def load(model_name: str, device: str):
        from sentence_transformers import CrossEncoder
        return CrossEncoder(model_name, device=device)

    def score(self, phrase: str, candidates: list[str]) -> list[float]:
        if not candidates:
            return []
        from ..cache import content_key
        key = content_key(stage="reranking", model=self.model_name, config={},
                          payload={"phrase": phrase, "candidates": candidates})
        cached = self.cache.get("reranking", key) if self.cache else None
        if cached is not None:
            return [float(value) for value in cached["scores"]]
        values = self.model.predict([(phrase, candidate) for candidate in candidates])
        result = [float(value) for value in values]
        if self.cache:
            self.cache.put("reranking", key, {"scores": result})
        return result

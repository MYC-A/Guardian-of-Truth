"""Optional dense encoders. The packer works without any of them."""
from __future__ import annotations

import math


class Embedder:
    """Interface: map texts to L2-normalised vectors (lists of floats)."""
    name = 'none'

    def encode(self, texts: list[str], *, is_query: bool) -> list[list[float]] | None:
        raise NotImplementedError


class NoEmbedder(Embedder):
    def encode(self, texts, *, is_query):
        return None


class FastEmbedEmbedder(Embedder):
    """ONNX multilingual encoder via ``fastembed`` (CPU, no torch).

    Default model is small and multilingual, which matters here: dialogue and
    targets are often Russian while policies, schemas and receipts are English.
    """

    def __init__(self, model='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                 query_prefix='', passage_prefix='', max_chars=2000):
        from fastembed import TextEmbedding  # optional dependency
        self.model = TextEmbedding(model)
        self.name = model
        self.query_prefix, self.passage_prefix, self.max_chars = query_prefix, passage_prefix, max_chars
        self._cache = {}

    def encode(self, texts, *, is_query):
        prefix = self.query_prefix if is_query else self.passage_prefix
        keys = [prefix + t[:self.max_chars] for t in texts]
        missing = [k for k in dict.fromkeys(keys) if k not in self._cache]
        if missing:
            for key, vector in zip(missing, self.model.embed(missing, batch_size=16)):
                values = [float(x) for x in vector]
                norm = math.sqrt(sum(x * x for x in values)) or 1.0
                self._cache[key] = [x / norm for x in values]
        return [self._cache[k] for k in keys]

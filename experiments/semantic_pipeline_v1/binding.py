"""semantic_pipeline_v1 — Phase 11: entity / tool / field binding.

Bind abstract semantic references (RuleIR target/atom text) to actual Guardian
entities (tool names, state fields):
  1. exact lexical/source match first (tool name appears verbatim in the text);
  2. local embedding retrieval over tool name + description texts (top-5);
  3. local CrossEncoder reranking of the candidates;
  4. UNKNOWN when ambiguity remains.
Embedding similarity is NEVER a proof: multiple plausible bindings are kept,
and unresolved ambiguity returns UNKNOWN with all candidates listed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


@dataclass
class BindingCandidate:
    name: str
    method: str                  # exact | embedding | crossencoder
    cosine: float | None = None
    crossencoder_score: float | None = None

    def as_dict(self) -> dict:
        return {"name": self.name, "method": self.method, "cosine": self.cosine,
                "crossencoder_score": self.crossencoder_score}


@dataclass
class BindingResult:
    semantic_text: str
    kind: str                    # action | state
    status: str                  # BOUND | AMBIGUOUS | UNKNOWN
    candidates: list[BindingCandidate] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"semantic_text": self.semantic_text, "kind": self.kind, "status": self.status,
                "candidates": [candidate.as_dict() for candidate in self.candidates]}


class Binder:
    """Holds the local models (embeddings + cross-encoder).  One instance per
    process; models stay resident (~1.0 GB total)."""

    def __init__(self):
        self._embedder = None
        self._reranker = None

    def _embed_model(self):
        if self._embedder is None:
            from retrieval import load_embedding_model
            self._embedder = load_embedding_model()
        return self._embedder

    def _rerank_model(self):
        if self._reranker is None:
            from sentence_transformers import CrossEncoder
            self._reranker = CrossEncoder("cross-encoder/nli-deberta-v3-small", device="cpu")
        return self._reranker

    def bind(self, semantic_text: str, names: list[str], descriptions: dict[str, str] | None = None,
             *, kind: str = "action", top_k: int = 5, bound_margin: float = 1.0,
             bound_score: float = 1.5) -> BindingResult:
        descriptions = descriptions or {}
        # 1. exact lexical match (verbatim tool/field name inside the text)
        exact = [name for name in sorted(names, key=len, reverse=True)
                 if name and re.search(r"(?<![\w.-])" + re.escape(name) + r"(?![\w.-])", semantic_text)]
        if len(exact) == 1:
            return BindingResult(semantic_text, kind, "BOUND",
                                 [BindingCandidate(exact[0], "exact", 1.0, None)])
        if len(exact) > 1:
            # multiple verbatim names: all kept, status AMBIGUOUS (never a vote)
            return BindingResult(semantic_text, kind, "AMBIGUOUS",
                                 [BindingCandidate(name, "exact", 1.0, None) for name in exact[:4]])
        if not names:
            return BindingResult(semantic_text, kind, "UNKNOWN", [])
        # 2. embedding retrieval over "name — description"
        texts = [f"{name} — {descriptions.get(name, '')}"[:400] for name in names]
        embedder = self._embed_model()
        import numpy as np
        query_vec = embedder.encode([semantic_text[:600]], normalize_embeddings=True)[0]
        doc_vecs = embedder.encode(texts, normalize_embeddings=True, batch_size=32,
                                   show_progress_bar=False)
        cosines = doc_vecs @ query_vec
        order = np.argsort(-cosines)[:top_k]
        pool = [(names[int(i)], float(cosines[int(i)])) for i in order]
        # 3. CrossEncoder rerank of the top-k candidates
        reranker = self._rerank_model()
        pairs = [(semantic_text[:600], f"{name} — {descriptions.get(name, '')}"[:600])
                 for name, _ in pool]
        try:
            # st-ce of nli-deberta: label ENTAILMENT index 1; use its logit as
            # the relevance score
            scores = reranker.predict(pairs)
            entailment = [float(row[1]) for row in scores]
        except Exception:
            entailment = [cosine for _, cosine in pool]
        ranked = sorted(zip(pool, entailment), key=lambda pair: -pair[1])
        candidates = [BindingCandidate(name, "crossencoder", cosine, round(score, 3))
                      for (name, cosine), score in ranked]
        best = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        if best[1] >= bound_score and (second is None or best[1] - second[1] >= bound_margin):
            return BindingResult(semantic_text, kind, "BOUND", candidates[:4])
        if best[1] >= bound_score * 0.6:
            return BindingResult(semantic_text, kind, "AMBIGUOUS", candidates[:4])
        return BindingResult(semantic_text, kind, "UNKNOWN", candidates[:4])


def tool_description_map(timeline) -> dict[str, str]:
    """{tool_name: description_text} from the catalog segments (deterministic)."""
    out: dict[str, str] = {}
    for segment in timeline.segments:
        if segment.source_type == "TOOL_DESCRIPTION" and segment.tool:
            out[segment.tool] = segment.text[:300]
    return out


def state_field_names(timeline) -> list[str]:
    """Field names from all catalog tool schemas (deterministic)."""
    fields: set[str] = set()
    for fragment in timeline.fragments:
        if fragment.source_type == "TOOL_SCHEMA" and fragment.kind == "tool_field":
            match = re.match(r"\s*(?:·\s*)?(\w+):", fragment.text)
            if match:
                fields.add(match.group(1))
    return sorted(fields)

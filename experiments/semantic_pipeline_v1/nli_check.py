"""semantic_pipeline_v1 — Phases 9 + 10: local NLI semantic check.

cross-encoder/nli-deberta-v3-small (284M, LOCAL CPU).  Label order verified
empirically: idx0=contradiction, idx1=entailment, idx2=neutral.

Role (FIREWALL, never a proof):
  - strong CONTRADICTION -> the candidate cannot be the only accepted
    interpretation (flagged, NOT silently deleted: disagreement is preserved
    as multiple candidates / unresolved);
  - NEUTRAL -> candidate remains uncertain;
  - ENTAILMENT -> candidate is supported (still not a mathematical guarantee).

Phase 10 lives here too: adversarial phrase-pair measurements demonstrating
why embeddings alone are insufficient for semantic validation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

MODEL_NAME = "cross-encoder/nli-deberta-v3-small"
LABELS = ("CONTRADICTION", "ENTAILMENT", "NEUTRAL")

# Phase 10 adversarial families: same words, opposite/negated meaning.
ADVERSARIAL_PAIRS = [
    ("verify before close", "close before verify"),
    ("The account must be verified before it is closed.", "The account may be closed before identity verification."),
    ("Identity verification is required before account closing.", "Account closing is required before identity verification."),
    ("You must perform the security check.", "You may perform the security check."),
    ("Approval requires at least two factors.", "Approval requires at most two factors."),
    ("Refunds are not allowed after departure.", "Refunds are allowed after departure."),
    ("Escalation is permitted only when all steps are exhausted.", "Escalation is permitted even when steps remain."),
    ("The upgrade is allowed if utilization is below 70%.", "The upgrade is allowed if utilization is above 70%."),
]


class NliChecker:
    def __init__(self, model_name: str = MODEL_NAME):
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name, device="cpu")

    def classify(self, pairs: list[tuple[str, str]]) -> list[dict]:
        self._load()
        scores = self._model.predict(pairs)
        out = []
        for (premise, hypothesis), score in zip(pairs, scores):
            index = int(score.argmax())
            out.append({"premise": premise, "hypothesis": hypothesis,
                        "label": LABELS[index],
                        "scores": {LABELS[i]: round(float(score[i]), 3) for i in range(3)}})
        return out

    def check_rule(self, source_text: str, rendered_hypothesis: str) -> dict:
        return self.classify([(source_text[:1600], rendered_hypothesis[:1600])])[0]


# ------------------------------------------------------------------ Phase 10

def embedding_similarity_demonstration(pairs=None, out_path: Path | None = None) -> dict:
    """Measure embedding cosine vs NLI on adversarial pairs.  Expected: high
    cosine despite reversed meaning -> justifies CrossEncoder/NLI for pairwise
    semantic checking and embeddings ONLY for candidate retrieval."""
    import numpy as np
    from retrieval import load_embedding_model
    pairs = pairs or ADVERSARIAL_PAIRS
    embedder = load_embedding_model()
    checker = NliChecker()
    left = [a for a, _ in pairs]
    right = [b for _, b in pairs]
    vectors_left = embedder.encode(left, normalize_embeddings=True)
    vectors_right = embedder.encode(right, normalize_embeddings=True)
    cosines = [float(vectors_left[i] @ vectors_right[i]) for i in range(len(pairs))]
    nli = checker.classify(pairs)
    rows = []
    for index, ((a, b), cosine) in enumerate(zip(pairs, cosines)):
        rows.append({
            "pair_index": index,
            "premise": a, "hypothesis": b,
            "embedding_cosine": round(cosine, 4),
            "nli_label": nli[index]["label"],
            "nli_scores": nli[index]["scores"],
            "nli_detects_difference": nli[index]["label"] == "CONTRADICTION",
        })
    result = {
        "embedding_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "nli_model": MODEL_NAME,
        "rows": rows,
        "mean_cosine_of_reversed_pairs": round(float(np.mean(cosines)), 4),
        "contradiction_detection_rate": round(
            sum(row["nli_detects_difference"] for row in rows) / len(rows), 4),
        "conclusion": (
            "Embedding cosine of semantically opposite pairs remains high "
            f"(mean {round(float(np.mean(cosines)), 3)}); the NLI cross-encoder labels "
            f"{sum(row['nli_detects_difference'] for row in rows)}/{len(rows)} of them "
            "CONTRADICTION. Embeddings are therefore used ONLY for candidate retrieval; "
            "pairwise semantic checking uses the NLI cross-encoder."
        ),
    }
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":  # pragma: no cover - manual run
    result = embedding_similarity_demonstration(
        out_path=REPO / "outputs" / "vnext" / "semantic_pipeline_v1" / "nli_adversarial_demo.json")
    print(json.dumps({key: result[key] for key in
                      ("mean_cosine_of_reversed_pairs", "contradiction_detection_rate", "conclusion")},
                     indent=1))
    for row in result["rows"]:
        print(f"cos={row['embedding_cosine']:.3f} nli={row['nli_label']:13s} | {row['premise'][:45]} vs {row['hypothesis'][:45]}")

"""Local NLI semantic firewall."""

from __future__ import annotations

import math

from ..types import NLIEvidence


class NLIFirewall:
    def __init__(self, model_name: str, model):
        self.model_name, self.model = model_name, model

    @staticmethod
    def load(model_name: str, device: str):
        from sentence_transformers import CrossEncoder
        return CrossEncoder(model_name, device=device)

    def check(self, premise: str, hypothesis: str) -> NLIEvidence:
        raw = self.model.predict([(premise, hypothesis)], apply_softmax=False)[0]
        logits = [float(item) for item in raw]
        offset = max(logits)
        exponentials = [math.exp(item - offset) for item in logits]
        total = sum(exponentials)
        values = [item / total for item in exponentials]
        mapping = getattr(getattr(self.model, "model", None), "config", None)
        id2label = getattr(mapping, "id2label", {}) or {}
        labels = []
        for index in range(len(values)):
            label = str(id2label.get(index, id2label.get(str(index), ""))).upper()
            labels.append(label if label in {"ENTAILMENT", "CONTRADICTION", "NEUTRAL"} else "")
        if set(labels) != {"ENTAILMENT", "CONTRADICTION", "NEUTRAL"}:
            # The verified checkpoint uses contradiction, entailment, neutral order.
            labels = ["CONTRADICTION", "ENTAILMENT", "NEUTRAL"]
        scores = {label: values[index] for index, label in enumerate(labels)}
        label = max(scores, key=scores.get)
        return NLIEvidence(label, scores, tuple(logits), self.model_name, hypothesis)

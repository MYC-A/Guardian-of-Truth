"""Optional span evidence only; no relation extraction is claimed."""

from __future__ import annotations


class GLiNEREvidenceExtractor:
    LABELS = ("ACTION", "STATE", "VALUE", "ENTITY", "CLAIM")

    def __init__(self, model_name: str, model):
        self.model_name, self.model = model_name, model

    @staticmethod
    def load(model_name: str, device: str):
        from gliner import GLiNER
        return GLiNER.from_pretrained(model_name, load_tokenizer=True).to(device)

    def extract(self, text: str) -> list[dict]:
        return [{"text": item.get("text"), "label": item.get("label"),
                 "start": item.get("start"), "end": item.get("end"),
                 "score": float(item.get("score", 0.0))}
                for item in self.model.predict_entities(text, list(self.LABELS))]

"""Honest LangExtract feature gate.

LangExtract is an orchestration library around an LLM provider. Installing it
does not itself provide local inference. V1 therefore executes only when a
configured provider callable is supplied; otherwise the stage is UNAVAILABLE.
"""

from __future__ import annotations

import importlib.util


class LangExtractUnavailable(RuntimeError):
    pass


class LangExtractAligner:
    def __init__(self, extractor=None, *, model_id: str | None = None):
        self.extractor = extractor
        self.model_id = model_id

    def status(self) -> dict:
        if importlib.util.find_spec("langextract") is None:
            return {"state": "UNAVAILABLE", "reason": "PACKAGE_NOT_INSTALLED",
                    "executed": False}
        if self.extractor is None or not self.model_id:
            return {"state": "UNAVAILABLE", "reason": "MODEL_PROVIDER_NOT_CONFIGURED",
                    "executed": False}
        return {"state": "EXECUTED", "reason": None, "executed": True,
                "model": self.model_id}

    def align(self, text: str, candidates: list[dict]) -> list[dict]:
        status = self.status()
        if status["state"] != "EXECUTED":
            raise LangExtractUnavailable(status["reason"])
        # The injected provider owns the LangExtract-specific prompt/examples.
        # This hook may attach grounding, but callers never use it as a judge.
        return list(self.extractor(text=text, candidates=candidates,
                                   model_id=self.model_id))

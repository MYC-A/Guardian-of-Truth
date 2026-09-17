"""Optional LangExtract alignment hook; never a semantic judge."""

from __future__ import annotations


class LangExtractAligner:
    def __init__(self, extractor=None):
        import langextract  # noqa: F401 - feature-gate dependency check
        self.extractor = extractor

    def align(self, text: str, candidates: list[dict]) -> list[dict]:
        # Production callers may inject a configured LangExtract pass. The V1
        # default merely preserves candidate spans; it cannot change meaning.
        if self.extractor is None:
            return candidates
        return list(self.extractor(text=text, candidates=candidates))

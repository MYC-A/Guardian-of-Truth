"""Optional LangExtract 1.7 grounding through explicit Mistral injection."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any, Callable

from .contracts import CaseInput, SourceLink, TheoryCandidate
from .grounding import validate_link


class MistralLangExtractGrounder:
    """Attach exact evidence spans without changing candidate semantics."""

    def __init__(self, *, model_id: str = "ministral-14b-latest",
                 base_url: str = "https://api.mistral.ai/v1",
                 api_key_env: str = "MISTRAL_API_KEY",
                 model_factory: Callable | None = None,
                 extract_fn: Callable | None = None,
                 example_factory: Callable | None = None):
        if model_id != "ministral-14b-latest":
            raise ValueError("Architecture B LangExtract model must be ministral-14b-latest")
        self.model_id, self.base_url, self.api_key_env = model_id, base_url, api_key_env
        self._model_factory, self._extract_fn = model_factory, extract_fn
        self._example_factory = example_factory
        self._model = None

    def _runtime(self):
        if self._model is None:
            key = os.environ.get(self.api_key_env)
            if not key:
                raise RuntimeError(f"missing API key environment variable: {self.api_key_env}")
            if self._model_factory is None or self._extract_fn is None:
                import langextract as lx
                from langextract.providers.openai import OpenAILanguageModel
                self._model_factory = self._model_factory or OpenAILanguageModel
                self._extract_fn = self._extract_fn or lx.extract
                self._example_factory = self._example_factory or (lambda: lx.data.ExampleData(
                    text="Identity must be verified before a refund.",
                    extractions=[lx.data.Extraction(
                        extraction_class="policy_evidence",
                        extraction_text="Identity must be verified before a refund.")]))
            self._model = self._model_factory(model_id=self.model_id, api_key=key,
                                              base_url=self.base_url, temperature=0.0,
                                              max_workers=1)
        return self._model, self._extract_fn

    @staticmethod
    def _links(result: Any, source_id: str, text: str) -> tuple[SourceLink, ...]:
        extractions = getattr(result, "extractions", None)
        if extractions is None and isinstance(result, dict):
            extractions = result.get("extractions", [])
        links = []
        for extraction in extractions or ():
            quote = (getattr(extraction, "extraction_text", None)
                     if not isinstance(extraction, dict) else extraction.get("extraction_text"))
            interval = (getattr(extraction, "char_interval", None)
                        if not isinstance(extraction, dict) else extraction.get("char_interval"))
            start = (getattr(interval, "start_pos", None)
                     if interval is not None and not isinstance(interval, dict)
                     else (interval or {}).get("start_pos") if isinstance(interval, dict) else None)
            end = (getattr(interval, "end_pos", None)
                   if interval is not None and not isinstance(interval, dict)
                   else (interval or {}).get("end_pos") if isinstance(interval, dict) else None)
            if isinstance(quote, str) and quote and isinstance(start, int) and isinstance(end, int):
                link = SourceLink(source_id, start, end, quote)
                if validate_link(link, {source_id: type("S", (), {"text": text})()})[0]:
                    links.append(link)
            elif isinstance(quote, str) and quote and text.count(quote) == 1:
                start = text.index(quote)
                links.append(SourceLink(source_id, start, start + len(quote), quote))
        # Multiple distinct proposals are ambiguous; never score-pick one.
        unique = tuple(dict.fromkeys(links))
        return unique if len(unique) == 1 else ()

    def ground(self, case: CaseInput, candidate: TheoryCandidate) -> TheoryCandidate:
        sources = {item.source_id: item for item in case.sources}
        grounded = []
        for element in candidate.elements:
            if element.source_links and all(validate_link(link, sources)[0]
                                            for link in element.source_links):
                grounded.append(element)
                continue
            model, extract_fn = self._runtime()
            proposals = []
            for source in case.sources:
                prompt = (
                    "Locate the exact source words that support this proposed policy interpretation. "
                    "Return only source text; do not validate, repair, or extend the interpretation. "
                    f"Proposed interpretation: {element.interpretation}"
                )
                examples = [self._example_factory()] if self._example_factory else []
                result = extract_fn(text_or_documents=source.text,
                                    prompt_description=prompt, examples=examples, model=model)
                proposals.extend(self._links(result, source.source_id, source.text))
            # One exact proposal across all documents is required.
            links = tuple(proposals) if len(proposals) == 1 else ()
            grounded.append(replace(element, source_links=links))
        return replace(candidate, elements=tuple(grounded))

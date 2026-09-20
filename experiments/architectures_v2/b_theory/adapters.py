"""Injectable model boundaries; implementations live outside this package."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .contracts import CaseInput, TheoryCandidate, Variant
from .orchestrator import run_case


class TheoryProvider(Protocol):
    """Adapter for Mistral, NuExtract, or another independent extractor."""

    def extract(self, case: CaseInput) -> Sequence[TheoryCandidate]: ...


class SourceGrounder(Protocol):
    """Optional LangExtract/source aligner adapter.

    It may propose links, but exact quote/offset acceptance remains in
    :mod:`grounding`; model agreement never bypasses that check.
    """

    def ground(self, case: CaseInput, candidate: TheoryCandidate) -> TheoryCandidate: ...


class MutualReviewer(Protocol):
    """Targeted repair adapter invoked only for B3."""

    def repair(self, case: CaseInput,
               parents: Sequence[TheoryCandidate]) -> Sequence[TheoryCandidate]: ...


def run_with_adapters(case: CaseInput, variant: Variant, *,
                      providers: Sequence[TheoryProvider],
                      source_grounder: SourceGrounder | None = None,
                      reviewers: Sequence[MutualReviewer] = ()) -> dict:
    candidates = [candidate for provider in providers for candidate in provider.extract(case)]
    if source_grounder is not None and variant in {Variant.B1, Variant.B2, Variant.B3}:
        candidates = [source_grounder.ground(case, candidate) for candidate in candidates]
    repairs = ([candidate for reviewer in reviewers
                for candidate in reviewer.repair(case, candidates)]
               if variant is Variant.B3 else [])
    return run_case(case, candidates, variant, repairs=repairs)

"""Replaceable semantic boundary. No model imports, network calls or weights.

A future local backend implements analyze(context) -> SemanticResult and is
injected into Detector(semantic=backend). Predictions remain hypotheses until a
separate, evaluated decision policy is implemented.
"""

from dataclasses import dataclass, field, replace
from typing import Protocol

from .types import Catalog, Event, EvidenceGraph, Finding, Obligation, SemanticChecker, Source


@dataclass
class AnalysisContext:
    prompt: str
    response: str
    history: list[Event]
    candidate: list[Event]
    catalog: Catalog
    obligations: list[Obligation]
    graph: EvidenceGraph
    evidence: list[Source]


@dataclass
class SemanticResult:
    findings: list[Finding] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


class SemanticAnalyzer(Protocol):
    name: str

    def analyze(self, context: AnalysisContext) -> SemanticResult: ...


class NoSemanticAnalyzer:
    name = 'none'

    def analyze(self, context: AnalysisContext) -> SemanticResult:
        return SemanticResult()


class LegacyCheckerAdapter:
    name = 'legacy_checker'

    def __init__(self, checker: SemanticChecker):
        self.checker = checker

    def analyze(self, context: AnalysisContext) -> SemanticResult:
        return SemanticResult(self.checker.review(context.prompt, context.response, context.evidence))


def run_semantic(backend: SemanticAnalyzer, context: AnalysisContext) -> SemanticResult:
    """Validate model output; a broken optional backend cannot erase exact checks.

    This is an output boundary, not a sandbox for untrusted Python plugins.
    Process isolation / runtime limits belong to a future model adapter.
    """
    try:
        result = backend.analyze(context)
        if not isinstance(result, SemanticResult):
            return SemanticResult(unresolved=['semantic_invalid_output'])
        if not isinstance(result.findings, list) or not isinstance(result.unresolved, list):
            return SemanticResult(unresolved=['semantic_invalid_output'])
        unresolved = [s for s in result.unresolved if isinstance(s, str)]
        accepted = []
        for finding in result.findings:
            if not isinstance(finding, Finding) or not isinstance(finding.sources, list):
                unresolved.append('semantic_invalid_finding')
                continue
            docs = {'prompt': context.prompt, 'response': context.response}
            valid_sources = all(isinstance(s, Source) and s.document in docs
                                and type(s.start) is int and type(s.end) is int
                                and 0 <= s.start < s.end <= len(docs[s.document])
                                for s in finding.sources)
            if not valid_sources or not isinstance(finding.code, str) or not isinstance(finding.message, str):
                unresolved.append('semantic_invalid_finding')
                continue
            if not finding.sources:
                unresolved.append('semantic_uncited_hypothesis')
            accepted.append(replace(finding, sources=list(finding.sources), status='hypothesis'))
        return SemanticResult(accepted, unresolved)
    except Exception:
        # Do not expose prompts, backend credentials or arbitrary exception text.
        return SemanticResult(unresolved=['semantic_backend_error'])

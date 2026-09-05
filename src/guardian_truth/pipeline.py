from .checks import check_calls
from .evidence import observations, retrieve
from .parsing import parse_catalog, parse_events
from .provenance import build_graph
from .semantic import (AnalysisContext, LegacyCheckerAdapter, NoSemanticAnalyzer,
                       SemanticAnalyzer, run_semantic)
from .types import EvidenceGraph, Obligation, Review, SemanticChecker


class Detector:
    def __init__(self, enabled=frozenset({'availability', 'schema', 'provenance'}),
                 checker: SemanticChecker | None = None, *, semantic: SemanticAnalyzer | None = None):
        self.enabled = frozenset(enabled)
        if self.enabled - {'availability', 'schema', 'provenance'}:
            raise ValueError('Unknown check family')
        if checker is not None and semantic is not None:
            raise ValueError('Pass semantic or the legacy checker, not both')
        self.semantic = (semantic if semantic is not None else
                         LegacyCheckerAdapter(checker) if checker is not None else NoSemanticAnalyzer())
        if not isinstance(getattr(self.semantic, 'name', None), str) or not self.semantic.name:
            raise ValueError('Semantic backend must have a nonempty string name')

    def review(self, prompt: str, response: str) -> Review:
        # Labels, explanations and example IDs intentionally absent from this API.
        if not isinstance(prompt, str) or not isinstance(response, str):
            raise TypeError('prompt and response must be strings')
        history = parse_events(prompt, 'prompt')
        candidate = parse_events(response, 'response')
        catalog = parse_catalog(history, prompt)
        findings, unresolved = check_calls(candidate, catalog, self.enabled)
        unresolved.extend(catalog.issues)
        if any(event.kind == 'text' for event in candidate):
            unresolved.append('text_meaning_not_verified')
        if any(event.kind == 'call' for event in candidate):
            unresolved.append('argument_provenance_and_policy_not_verified')
        if not candidate: unresolved.append('empty_response')
        obligations = []
        for event in candidate:
            checks = (['availability', 'schema', 'provenance', 'preconditions']
                      if event.kind == 'call' else ['meaning', 'support', 'materiality'])
            obligation = Obligation(event.kind, event.source, checks)
            if any(event.source in finding.sources and finding.status == 'violation' for finding in findings):
                obligation.status = 'violation'
            obligations.append(obligation)
        evidence = retrieve(history, prompt, response)
        graph = build_graph(history, candidate) if 'provenance' in self.enabled else EvidenceGraph()
        unresolved.extend(graph.issues)
        context = AnalysisContext(prompt, response, history, candidate, catalog, obligations, graph, evidence)
        semantic_result = run_semantic(self.semantic, context)
        findings.extend(semantic_result.findings)
        unresolved.extend(semantic_result.unresolved)
        status = 'violation' if any(f.status == 'violation' for f in findings) else 'unknown'
        return Review(findings, obligations, sorted(set(unresolved)), observations(history), evidence,
                      sorted(self.enabled), status, graph=graph, semantic_backend=self.semantic.name)

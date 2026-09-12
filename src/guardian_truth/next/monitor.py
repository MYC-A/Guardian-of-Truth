"""Composition root for the minimal Compiled Evidential Monitor arm (X5)."""

from __future__ import annotations

from guardian_truth.pipeline import Detector

from .binder import bind_claims
from .claims import extract_claims_with_coverage
from .decision_adapter import to_binary
from .normalize import build_evidence, normalize_trace
from .policy import compile_policy
from .records import FourValue, MonitorResult, PropositionResult
from .solver import (
    InterpretationResult, Obligation, ObligationEvaluation, ObligationKind, solve,
)


def review(prompt: str, response: str, *, unknown_label: int = 0, contracts=None) -> MonitorResult:
    policy = compile_policy(prompt, arm="P0")
    events = normalize_trace(prompt, response)
    evidence = build_evidence(events, contracts)
    extraction = extract_claims_with_coverage(response)
    claims = list(extraction.claims)
    bindings = bind_claims(claims, evidence)

    incumbent = Detector().review(prompt, response)
    violations = [finding for finding in incumbent.findings if finding.status == "violation"]
    propositions = [
        PropositionResult(
            proposition=finding.code,
            value=FourValue.TRUE,
            reason="incumbent_exact_finding",
        )
        for finding in violations
    ]
    solver_evaluations = tuple(
        ObligationEvaluation(
            Obligation(f"incumbent:{index}", ObligationKind.STATE_INVARIANT,
                       ("no_material_violation", finding.code)),
            FourValue.FALSE,
            completeness_sufficient=True,
            reason="incumbent_exact_finding",
        )
        for index, finding in enumerate(violations)
    )
    solved = solve((InterpretationResult("incumbent_exact", solver_evaluations),))
    decision = to_binary(solved, unresolved_label=unknown_label)
    status = {
        "PROVED_ERROR": FourValue.TRUE,
        "PROVED_NO_ERROR": FourValue.FALSE,
        "INCONSISTENT": FourValue.BOTH,
        "UNRESOLVED": FourValue.UNKNOWN,
    }[solved.verdict.value]
    return MonitorResult(
        status=status,
        label=decision.label,
        used_fallback=decision.used_fallback,
        policy=policy,
        events=events,
        evidence=evidence,
        claims=claims,
        bindings=bindings,
        propositions=propositions,
        diagnostics=list(incumbent.unresolved) + [solved.reason] + [
            "claim_coverage_incomplete" for item in extraction.coverage if item.status == "UNKNOWN"
        ],
        internal_verdict=solved.verdict.value,
        binary_mapping_version=decision.mapping_version,
    )

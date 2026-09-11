"""Composition root for the minimal Compiled Evidential Monitor arm (X5)."""

from __future__ import annotations

from guardian_truth.pipeline import Detector

from .binder import bind_claims
from .claims import extract_claims
from .normalize import build_evidence, normalize_trace
from .policy import compile_policy
from .records import FourValue, MonitorResult, PropositionResult


def review(prompt: str, response: str, *, unknown_label: int = 0) -> MonitorResult:
    policy = compile_policy(prompt, arm="P0")
    events = normalize_trace(prompt, response)
    evidence = build_evidence(events)
    claims = extract_claims(response)
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
    if violations:
        status, label, fallback = FourValue.TRUE, 1, False
    else:
        # Unsupported claims remain unknown.  They are not silently converted
        # to false, even though the competition adapter needs a binary label.
        status, label, fallback = FourValue.UNKNOWN, unknown_label, True
    return MonitorResult(
        status=status,
        label=label,
        used_fallback=fallback,
        policy=policy,
        events=events,
        evidence=evidence,
        claims=claims,
        bindings=bindings,
        propositions=propositions,
        diagnostics=list(incumbent.unresolved),
    )

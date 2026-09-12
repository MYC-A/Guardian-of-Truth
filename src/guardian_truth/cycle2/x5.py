"""Cycle 2 X5_CORE and X5_PROTECTED with mandatory execution telemetry."""

from __future__ import annotations

from guardian_truth.pipeline import Detector
from guardian_truth.next.binder import bind_claims
from guardian_truth.next.claims import extract_claims_with_coverage
from guardian_truth.next.effects import load_human_contracts, merge_human_contracts, schema_registry
from guardian_truth.next.normalize import build_evidence, normalize_trace
from guardian_truth.next.policy import compile_policy
from guardian_truth.next.records import FourValue
from guardian_truth.next.solver import (
    InterpretationResult,
    Obligation,
    ObligationEvaluation,
    ObligationKind,
    solve,
)


def _structural_evaluations(policy, events) -> list[ObligationEvaluation]:
    target = [event for event in events if event.source.document == "response"]
    calls = [event for event in target if event.role == "assistant" and event.kind == "call"]
    messages = [event for event in target if event.role == "assistant" and event.kind == "text"
                and event.raw_payload.strip()]
    rows = []
    for rule in policy.rules:
        if rule.predicate == "max_tool_calls":
            satisfied = FourValue.TRUE if len(calls) <= int(rule.object) else FourValue.FALSE
            rows.append(ObligationEvaluation(
                Obligation("x5:" + rule.id, ObligationKind.STATE_INVARIANT,
                           ("max_tool_calls", str(rule.object)), (rule.id,)),
                satisfied, completeness_sufficient=True,
                reason="exact_response_call_count",
            ))
        elif rule.predicate == "text_xor_tool_call":
            satisfied = FourValue.TRUE if bool(calls) != bool(messages) else FourValue.FALSE
            rows.append(ObligationEvaluation(
                Obligation("x5:" + rule.id, ObligationKind.RESPONSE,
                           ("text_xor_tool_call",), (rule.id,)),
                satisfied, completeness_sufficient=True,
                reason="exact_response_channel_count",
            ))
    return rows


def core_review(prompt: str, response: str, *, t1_contract_path=None) -> dict:
    """Run only new components; never consult Detector findings."""
    policy = compile_policy(prompt, arm="X5_CORE")
    events = normalize_trace(prompt, response)
    contracts = schema_registry(prompt)
    if t1_contract_path is not None:
        trusted = load_human_contracts(t1_contract_path)
        relevant = {name: item for name, item in trusted.items() if name in contracts}
        contracts = merge_human_contracts(contracts, relevant)
    evidence = build_evidence(events, contracts)
    extraction = extract_claims_with_coverage(response)
    claims = list(extraction.claims)
    bindings = bind_claims(claims, evidence)
    evaluations = _structural_evaluations(policy, events)
    for index, binding in enumerate(bindings):
        evaluations.append(ObligationEvaluation(
            Obligation(f"x5:claim:{index}", ObligationKind.CLAIM_SUPPORT, (binding.claim_id,)),
            binding.status, binding.evidence_ids,
            completeness_sufficient=False,
            reason=binding.reason,
        ))
    solved = solve((InterpretationResult("x5_core", tuple(evaluations)),))
    binary = 1 if solved.verdict.value == "PROVED_ERROR" else 0
    fallback = solved.verdict.value in {"UNRESOLVED", "INCONSISTENT"}
    unknown_policy = sum(item.status in {"UNKNOWN", "UNSUPPORTED"} for item in policy.coverage)
    unknown_claims = sum(item.status == "UNKNOWN" for item in extraction.coverage)
    unknown_tools = sum(not contract.guaranteed_effects and not contract.writes
                        and contract.provenance == "T0_schema_name" for contract in contracts.values())
    policy_status = (
        "SUPPORTED" if policy.rules and not unknown_policy else
        "PARTIAL" if policy.rules else "UNKNOWN"
    )
    telemetry = {
        "policy_status": policy_status,
        "policy_arm": policy.compiler_arm,
        "n_policy_segments": len(policy.segments),
        "n_policy_rules": len(policy.rules),
        "n_unknown_policy_segments": unknown_policy,
        "n_claim_spans": len(extraction.coverage),
        "n_claims": len(claims),
        "n_unknown_claim_spans": unknown_claims,
        "n_tool_contracts": len(contracts),
        "n_unknown_tools": unknown_tools,
        "n_evidence_events": len(evidence),
        "n_candidate_bindings": len(bindings),
        "solver_status": solved.verdict.value,
        "binary_result": binary,
        "decision_source": "FALLBACK" if fallback else "X5_CORE",
        "solver_reason": solved.reason,
        "used_binary_fallback": fallback,
    }
    return {"label": binary, "internal_verdict": solved.verdict.value,
            "telemetry": telemetry}


def protected_review(prompt: str, response: str, *, t1_contract_path=None) -> dict:
    core = core_review(prompt, response, t1_contract_path=t1_contract_path)
    incumbent = Detector().review(prompt, response)
    x0 = int(incumbent.status == "violation")
    label = int(bool(x0 or core["label"]))
    if x0 and core["label"]:
        source = "BOTH"
    elif x0:
        source = "X0"
    elif core["label"]:
        source = "X5_CORE"
    elif core["telemetry"]["used_binary_fallback"]:
        source = "FALLBACK"
    else:
        source = "DEFAULT"
    telemetry = dict(core["telemetry"])
    telemetry.update({"binary_result": label, "decision_source": source, "x0_binary": x0})
    return {"label": label, "internal_verdict": core["internal_verdict"],
            "telemetry": telemetry}

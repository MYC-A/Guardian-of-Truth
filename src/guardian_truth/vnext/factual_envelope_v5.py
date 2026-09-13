"""Source envelope -> native C2 once -> field/history layers -> scoped receipts.

Runnable factual integration, not a substitute for whole Core/world composition.
No implicit API client, keys, Goal v3 or LLM-to-T1 promotion.
"""

from dataclasses import dataclass

from .claim_field_bindings_v3 import interpret_graph_result_fields
from .claim_method_bindings_v5 import bind_native_method_claim
from .claim_method_certificate_v5 import make_claim_method_receipt, validate_claim_method_receipt
from .claims import build_claim_graph
from .envelope_field_certificate_v4 import check_envelope_field_evidence, make_envelope_field_receipt
from .identity_aliases_v2 import IdentityAliasIndex
from .source_envelope_v4 import normalize_envelope
from .temporal_queries_v4 import TemporalQueryIndex
from .types import ClaimKind, Diagnostics, Disposition, Reason, Truth


@dataclass(frozen=True)
class EnvelopeFactualAnalysisV5:
    source: object
    graph: object
    field_evidence: object
    method_evidence: tuple
    field_receipt: object | None
    method_receipt: object | None
    field_receipt_valid: bool
    method_receipt_valid: bool
    diagnostics: Diagnostics
    scope: str = "CONDITIONAL_NATIVE_FACTUAL_FIELD_AND_METHOD_LAYER_NOT_WHOLE_CORE"


def analyze_envelope_factual_v5(envelope, snapshots, registry, methods, backend):
    snapshots, methods = tuple(snapshots), tuple(methods)
    source = normalize_envelope(envelope)
    graph = build_claim_graph(envelope.response, backend)
    identity_declarations = tuple(item.identity for item in snapshots)
    fields = interpret_graph_result_fields(envelope.response, graph, IdentityAliasIndex(source.ledger, identity_declarations), backend)
    field_checked = check_envelope_field_evidence(envelope, identity_declarations, graph, fields)
    field_receipt = make_envelope_field_receipt(envelope, identity_declarations, graph, fields) if field_checked.valid else None
    index = TemporalQueryIndex(source.ledger, snapshots, registry, methods)
    causality = dict(graph.explicit_causality)
    method_rows = tuple(bind_native_method_claim(envelope, claim, index, backend, explicit_causality=causality.get(claim.claim_id)) for claim in graph.claims)
    try:
        method_receipt = make_claim_method_receipt(envelope, snapshots, registry, methods, graph, method_rows)
        method_valid = validate_claim_method_receipt(method_receipt, envelope, snapshots, registry, methods, graph, method_rows)
    except ValueError:
        method_receipt, method_valid = None, False
    method_kinds = {ClaimKind.ACTION_COMPLETED, ClaimKind.ABSENCE}
    active_rows = tuple(method_rows[i] if claim.kind in method_kinds else fields.claims[i] for i, claim in enumerate(graph.claims))
    causal_blocked = tuple(claim.claim_id for claim in graph.claims if claim.disposition is not Disposition.NON_VERIFIABLE
        and causality.get(claim.claim_id) is not False)
    reasons = tuple(dict.fromkeys([*source.reasons, *[reason for _, reason in graph.failures],
        *[reason for row in active_rows if row.disposition is not Disposition.NON_VERIFIABLE for reason in row.reasons],
        *([Reason.CAUSALITY_UNPROVED] if causal_blocked else []),
        *([Reason.EVIDENCE_INCOMPLETE] if not field_checked.valid or not method_valid else [])]))
    blocked = tuple(row.claim_id for row in active_rows if row.disposition is not Disposition.NON_VERIFIABLE
        and (row.value is Truth.UNKNOWN or row.claim_id in causal_blocked))
    missing = tuple(dict.fromkeys([term for row in active_rows for term in row.unresolved_terms]
        + ["factual_lowering_or_evidence_unknown:" + cid for cid in blocked]
        + ["unlowered_causal_obligation:" + cid for cid in causal_blocked] + list(field_checked.errors)))
    return EnvelopeFactualAnalysisV5(source, graph, fields, method_rows, field_receipt, method_receipt, field_checked.valid, method_valid,
        Diagnostics(reasons[0] if reasons else None, reasons[1:], blocked, (), missing, ()))

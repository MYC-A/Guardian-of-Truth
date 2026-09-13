"""Explicit source envelope -> C2 -> indexed fields -> independent receipt.

This source-safe field layer is intended for joint Core integration. It does
not replace a whole-Core verdict, interpret Goal v3 or construct an API client.
"""

from dataclasses import dataclass

from .claim_field_bindings_v3 import GraphFieldEvidence, interpret_graph_result_fields
from .claim_field_certificate_v3 import FieldEvidenceCheck
from .claims import ClaimGraph, build_claim_graph
from .envelope_field_certificate_v4 import EnvelopeFieldReceipt, check_envelope_field_evidence, check_envelope_field_receipt, make_envelope_field_receipt
from .identity_aliases_v2 import IdentityAliasIndex
from .source_envelope_v4 import EnvelopeNormalization, normalize_envelope
from .types import Diagnostics, Disposition, Reason, Truth


@dataclass(frozen=True)
class EnvelopeFactualAnalysis:
    source: EnvelopeNormalization
    graph: ClaimGraph
    evidence: GraphFieldEvidence
    receipt: EnvelopeFieldReceipt | None
    receipt_check: FieldEvidenceCheck
    diagnostics: Diagnostics
    scope: str = "ENVELOPE_FIELD_ATTRIBUTION_LAYER_ONLY_NOT_FULL_CORE"


def analyze_envelope_factual_fields(envelope, declarations, backend):
    declarations = tuple(declarations)
    normalized = normalize_envelope(envelope)
    graph = build_claim_graph(envelope.response, backend)
    index = IdentityAliasIndex(normalized.ledger, declarations)
    evidence = interpret_graph_result_fields(envelope.response, graph, index, backend)
    checked = check_envelope_field_evidence(envelope, declarations, graph, evidence)
    receipt = make_envelope_field_receipt(envelope, declarations, graph, evidence) if checked.valid else None
    if receipt is not None:
        checked = check_envelope_field_receipt(receipt, envelope, declarations, graph, evidence)
    reasons = tuple(dict.fromkeys([*normalized.reasons, *[reason for _, reason in graph.failures],
        *[reason for row in evidence.claims for reason in row.reasons],
        *([Reason.EVIDENCE_INCOMPLETE] if not checked.valid else [])]))
    blocked = tuple(row.claim_id for row in evidence.claims
        if row.disposition is not Disposition.NON_VERIFIABLE and row.value is Truth.UNKNOWN)
    missing = tuple(dict.fromkeys([term for row in evidence.claims for term in row.unresolved_terms]
        + ["field_lowering_or_evidence_unknown:" + cid for cid in blocked] + list(checked.errors)))
    priorities = (Reason.TRANSPORT_ERROR, Reason.SCHEMA_ERROR, Reason.SOURCE_UNBOUND, Reason.EVIDENCE_INCOMPLETE)
    primary = min(reasons, key=lambda reason: priorities.index(reason) if reason in priorities else len(priorities)) if reasons else None
    diagnostics = Diagnostics(primary, tuple(reason for reason in reasons if reason is not primary), blocked, (), missing, ())
    return EnvelopeFactualAnalysis(normalized, graph, evidence, receipt if checked.valid else None, checked, diagnostics)

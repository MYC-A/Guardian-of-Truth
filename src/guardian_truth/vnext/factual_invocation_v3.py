"""Runnable source -> C2 graph -> indexed field evidence -> independent receipt.

Only result-field attribution has the new value-aware lowering here. Other
claim kinds stay explicit; no separate layer is advertised as a full Core.
"""

from dataclasses import dataclass

from .claim_field_bindings_v3 import GraphFieldEvidence, interpret_graph_result_fields
from .claim_field_certificate_v3 import FieldEvidenceCheck, FieldEvidenceReceipt, check_field_evidence, check_field_receipt, make_field_receipt
from .claims import ClaimGraph, build_claim_graph
from .identity_aliases_v2 import IdentityAliasIndex, IdentityDeclaration
from .ledger import EvidenceLedger
from .normalize_source_v3 import normalize_source
from .types import Diagnostics, Disposition, Reason, ToolIdentity, Truth


@dataclass(frozen=True)
class FactualInvocationInput:
    prompt: str
    response: str
    tool_metadata: tuple[ToolIdentity, ...] = ()
    identity_declarations: tuple[IdentityDeclaration, ...] = ()
    history_complete: bool = False
    completeness_basis: str | None = None


@dataclass(frozen=True)
class FactualInvocationAnalysis:
    ledger: EvidenceLedger
    graph: ClaimGraph
    evidence: GraphFieldEvidence
    receipt: FieldEvidenceReceipt | None
    receipt_check: FieldEvidenceCheck
    diagnostics: Diagnostics
    scope: str = 'FIELD_ATTRIBUTION_LAYER_ONLY_NOT_FULL_CORE'


def analyze_factual_fields(data, backend):
    ledger = EvidenceLedger.from_events(normalize_source(data.prompt, data.response, tool_identities=data.tool_metadata),
        history_complete=data.history_complete, completeness_basis=data.completeness_basis)
    graph = build_claim_graph(data.response, backend)
    source = IdentityAliasIndex(ledger, data.identity_declarations)
    evidence = interpret_graph_result_fields(data.response, graph, source, backend)
    arguments = (data.prompt, data.response, data.tool_metadata, data.identity_declarations, graph, evidence)
    settings = {'history_complete': data.history_complete, 'completeness_basis': data.completeness_basis}
    checked = check_field_evidence(*arguments, **settings)
    receipt = make_field_receipt(*arguments, **settings) if checked.valid else None
    if receipt is not None:
        checked = check_field_receipt(receipt, *arguments, **settings)
    reasons = tuple(dict.fromkeys([reason for _, reason in graph.failures]
        + [reason for row in evidence.claims for reason in row.reasons]
        + ([Reason.EVIDENCE_INCOMPLETE] if not checked.valid else [])))
    blocked = tuple(row.claim_id for row in evidence.claims
        if row.disposition is not Disposition.NON_VERIFIABLE and row.value is Truth.UNKNOWN)
    missing = tuple(dict.fromkeys([term for row in evidence.claims for term in row.unresolved_terms]
        + [f'field_lowering_or_evidence_unknown:{cid}' for cid in blocked] + list(checked.errors)))
    priorities = [Reason.TRANSPORT_ERROR, Reason.SCHEMA_ERROR, Reason.CLAIM_UNTYPED, Reason.ENTITY_UNBOUND,
        Reason.ENTITY_AMBIGUOUS, Reason.EVIDENCE_INCOMPLETE]
    primary = min(reasons, key=lambda reason: priorities.index(reason) if reason in priorities else len(priorities)) if reasons else None
    diagnostics = Diagnostics(primary, tuple(reason for reason in reasons if reason is not primary), blocked, (), missing, ())
    return FactualInvocationAnalysis(ledger, graph, evidence, receipt if checked.valid else None, checked, diagnostics)

"""Independent lexical/source/entity replay for conditional native method receipts.

No semantic backend, candidate binder or query/index generation is invoked.
The claim meaning remains an explicit assumption, not an entailment proof.
"""

from dataclasses import asdict, dataclass
import re

from guardian_truth.cycle2.claims import response_spans
from .claim_method_bindings_v5 import SCOPE, allowed_method_claim, method_meanings
from .identity_aliases_v2 import records_at
from .integrity import canonical, digest
from .source_envelope_v4 import normalize_envelope
from .temporal_certificate_v4 import validate_temporal_certificate
from .temporal_queries_v4 import TemporalQuery
from .types import CoverageStatus, Disposition, EntityRef, Truth

ASSUMPTIONS = (
    "application authenticates source frames and authoritative tool/resource declarations",
    "conditional on supplied C2 fields and every retained source method meaning; no NL entailment/closure claimed",
    "all compatible source-owned ID/historical-alias bindings are enumerated within the supplied source",
    "method mutation history only; not current state, exclusive causation, goal authorization or Core verdict",
)


@dataclass(frozen=True)
class ClaimMethodReceipt:
    version: str
    source_sha256: str
    evidence_sha256: str
    assumptions: tuple[str, ...]
    scope: str = SCOPE


def source_hash(envelope, snapshots, registry, methods, graph):
    return digest({"envelope": asdict(envelope), "snapshots": [asdict(item) for item in snapshots],
        "contracts": [asdict(item) for item in registry.contracts], "methods": [asdict(item) for item in methods], "graph": asdict(graph)})


def check_claim_method_evidence(envelope, snapshots, registry, methods, graph, rows):
    errors = []
    spans = {item["span_id"]: (item["start"], item["end"]) for item in response_spans(envelope.response)}
    claims = {claim.claim_id: claim for claim in graph.claims}
    evidence = {row.claim_id: row for row in rows}
    causality = dict(graph.explicit_causality)
    if graph.response_sha256 != digest(envelope.response) or len(claims) != len(graph.claims) or set(claims) != set(spans):
        errors.append("CLAIM_SOURCE_OR_INVENTORY_CHANGED")
    if len(evidence) != len(rows) or set(evidence) != set(claims):
        errors.append("CLAIM_DROPPED_OR_DUPLICATED")
    if len(causality) != len(graph.explicit_causality) or set(causality) != set(claims):
        errors.append("CAUSAL_DISPOSITION_INVENTORY_CHANGED")
    catalog = {meaning.meaning_id: meaning for meaning in method_meanings(methods)}
    ledger = normalize_envelope(envelope).ledger
    limit = max((event.index for event in ledger.events if event.source.document == "prompt"), default=-1)
    observed = []
    declarations = {item.identity.tool: item.identity for item in snapshots}
    for event in ledger.events:
        if event.index > limit or event.kind != "result" or event.actor != "tool" or event.payload_json is None or event.pairing_issue:
            continue
        declaration = declarations.get(event.tool)
        if declaration is None:
            continue
        for record, _ in records_at(event.payload, declaration.record_path):
            id_type = str if declaration.id_type == "string" else int
            if not isinstance(record, dict) or type(record.get(declaration.id_field)) is not id_type or not str(record[declaration.id_field]):
                continue
            aliases = []
            for field in declaration.alias_fields:
                value = record.get(field)
                values = value if isinstance(value, list) else [value]
                aliases.extend(item for item in values if isinstance(item, str) and item)
            observed.append((EntityRef(declaration.id_field, str(record[declaration.id_field]), declaration.namespace), tuple(aliases)))
    for cid, claim in claims.items():
        if claim.span.document != "response" or (claim.span.start, claim.span.end) != spans.get(cid):
            errors.append("DETERMINISTIC_SPAN_CHANGED:" + cid)
        row = evidence.get(cid)
        if row is None:
            continue
        if row.scope != SCOPE or row.disposition != claim.disposition or row.kind != claim.kind:
            errors.append("METHOD_SCOPE_OR_DISPOSITION_CHANGED:" + cid)
        if not allowed_method_claim(envelope.response, claim) or causality.get(cid) is not False:
            if row.meanings or row.bindings or row.value is not Truth.UNKNOWN or row.candidate_set_complete or row.coverage is not CoverageStatus.OPEN_SEMANTICS:
                errors.append("UNSUPPORTED_CLAIM_USED_AS_METHOD_FACT:" + cid)
            continue
        if len({meaning.meaning_id for meaning in row.meanings}) != len(row.meanings) or any(catalog.get(meaning.meaning_id) != meaning for meaning in row.meanings):
            errors.append("SOURCE_METHOD_MEANING_CHANGED:" + cid)
            continue
        if not row.meanings:
            if row.bindings or row.value is not Truth.UNKNOWN or row.candidate_set_complete or row.coverage is not CoverageStatus.OPEN_SEMANTICS:
                errors.append("EMPTY_METHOD_MEANING_HAS_FACT:" + cid)
            continue
        text = envelope.response[claim.span.start:claim.span.end]
        refs = {ref for ref in claim.entity_refs if ref and re.search(r"(?<!\w)" + re.escape(ref) + r"(?!\w)", text)}
        expected_bindings, missing = {}, False
        for meaning in row.meanings:
            id_types = {item.identity.id_type for item in snapshots
                if item.identity.namespace == meaning.namespace and item.identity.id_field == meaning.id_field}
            if id_types != {"string"}:
                missing = True
                continue
            entities = {entity for entity, aliases in observed if entity.namespace == meaning.namespace and entity.key == meaning.id_field
                and any(ref == entity.value or ref in aliases for ref in refs)}
            if any(not any(entity.namespace == meaning.namespace and entity.key == meaning.id_field
                    and (ref == entity.value or ref in aliases) for entity, aliases in observed) for ref in refs):
                missing = True
            if not entities:
                missing = True
            for entity in entities:
                expected_bindings[(meaning.meaning_id, entity)] = TemporalQuery("METHOD_HISTORY", "id", entity.value, meaning.namespace,
                    meaning.id_field, canonical(claim.polarity == "POSITIVE").decode(), actor=claim.actor.lower(),
                    method_identities=meaning.identities, argument_entity_path=meaning.argument_entity_path, effect_predicate=meaning.effect_predicate,
                    before_index=limit if limit >= 0 else None, method_effect_value_json=meaning.effect_value_json)
        actual = {(binding.meaning_id, binding.evidence.bindings[0].entity): binding for binding in row.bindings if len(binding.evidence.bindings) == 1}
        if len(actual) != len(row.bindings) or set(actual) != set(expected_bindings):
            errors.append("METHOD_ENTITY_BINDING_DROPPED_OR_DUPLICATED:" + cid)
        valid = True
        for key, binding in actual.items():
            if binding.evidence.query != expected_bindings.get(key):
                errors.append("CLAIM_METHOD_QUERY_CHANGED:" + cid)
            checked = validate_temporal_certificate(binding.receipt, envelope, snapshots, registry, methods, binding.evidence)
            if binding.receipt_valid != checked or not checked:
                errors.append("TEMPORAL_METHOD_RECEIPT_INVALID:" + cid)
                valid = False
        values = {binding.evidence.value for binding in row.bindings}
        expected_value = next(iter(values)) if len(values) == 1 and not missing and not row.unresolved_terms and valid else Truth.UNKNOWN
        if row.value is not expected_value:
            errors.append("METHOD_MEANING_BINDING_CONSENSUS_CHANGED:" + cid)
        complete = not missing and all(binding.evidence.candidate_set_complete and binding.receipt_valid for binding in row.bindings)
        if row.candidate_set_complete != complete:
            errors.append("METHOD_BINDING_COMPLETENESS_CHANGED:" + cid)
        expected_coverage = CoverageStatus.OPEN_SEMANTICS if missing or row.unresolved_terms else CoverageStatus.EMPIRICALLY_COVERED
        if row.coverage is not expected_coverage:
            errors.append("LLM_METHOD_MEANING_FALSELY_CLOSED:" + cid)
    return tuple(dict.fromkeys(errors))


def make_claim_method_receipt(envelope, snapshots, registry, methods, graph, rows):
    if check_claim_method_evidence(envelope, snapshots, registry, methods, graph, rows):
        raise ValueError("native method evidence failed independent source recheck")
    return ClaimMethodReceipt("guardian-conditional-native-method-receipt-v5", source_hash(envelope, snapshots, registry, methods, graph),
        digest([asdict(row) for row in rows]), ASSUMPTIONS)


def validate_claim_method_receipt(receipt, envelope, snapshots, registry, methods, graph, rows):
    expected = ClaimMethodReceipt("guardian-conditional-native-method-receipt-v5", source_hash(envelope, snapshots, registry, methods, graph),
        digest([asdict(row) for row in rows]), ASSUMPTIONS)
    return receipt == expected and not check_claim_method_evidence(envelope, snapshots, registry, methods, graph, rows)

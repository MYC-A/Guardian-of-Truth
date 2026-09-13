"""Independent envelope/record recheck, with a distinct conditional receipt.

No binder, semantic backend or solver is invoked. Shared lexical inventories
and primitive field checks are deterministic; the candidate index is rebuilt.
"""

from dataclasses import asdict, dataclass
import re

from guardian_truth.cycle2.claims import response_spans
from guardian_truth.parsing import decode_json
from .claim_field_bindings_v3 import field_paths, target_literals
from .claim_field_certificate_v3 import FieldEvidenceCheck
from .identity_aliases_v2 import IdentityAliasIndex
from .integrity import digest
from .scoped_result_evidence_v2 import ScopedFieldQuery, prove_scoped_field
from .source_envelope_v4 import normalize_envelope
from .types import ClaimKind, Disposition, Reason, Truth


ASSUMPTIONS = (
    ("SOURCE", "application authenticates adapter-owned source framing; hashes do not prove authorship"),
    ("MEANINGS", "conditional retained field/literal mappings; unrestricted NL completeness not asserted"),
    ("EVIDENCE", "all compatible exact original TOOL-result records under source-owned identity declarations"),
    ("SCOPE", "field attribution only; not current state, completion, causality or Core safety"),
)


@dataclass(frozen=True)
class EnvelopeFieldReceipt:
    version: str
    source_sha256: str
    evidence_sha256: str
    assumptions: tuple[tuple[str, str], ...]


def source_hash(envelope, declarations, graph):
    return digest({"envelope": asdict(envelope), "declarations": [asdict(item) for item in declarations], "graph": asdict(graph)})


def check_envelope_field_evidence(envelope, declarations, graph, evidence):
    normalized = normalize_envelope(envelope)
    ledger, response, errors = normalized.ledger, envelope.response, []
    if graph.response_sha256 != digest(response) or evidence.response_sha256 != graph.response_sha256:
        errors.append("TARGET_SOURCE_HASH_MISMATCH")
    if evidence.identity_declarations_sha256 != digest([asdict(item) for item in declarations]):
        errors.append("IDENTITY_DECLARATION_HASH_MISMATCH")
    spans = {item["span_id"]: (item["start"], item["end"]) for item in response_spans(response)}
    claims = {claim.claim_id: claim for claim in graph.claims}
    rows = {row.claim_id: row for row in evidence.claims}
    if (len(claims) != len(graph.claims) or set(claims) != set(spans)
            or any(claim.span.document != "response" or (claim.span.start, claim.span.end) != spans.get(claim.claim_id)
                for claim in graph.claims)):
        errors.append("DETERMINISTIC_SPAN_INVENTORY_MISMATCH")
    if len(rows) != len(evidence.claims) or set(rows) != set(claims):
        errors.append("CLAIM_DROPPED_OR_DUPLICATED")
    if evidence.failures != tuple((row.claim_id, reason) for row in evidence.claims for reason in row.reasons
            if reason in {Reason.TRANSPORT_ERROR, Reason.SCHEMA_ERROR}):
        errors.append("COMPONENT_FAILURE_AUDIT_CHANGED")
    source = IdentityAliasIndex(ledger, declarations)
    direct, records_by_entity = {}, {}
    for (entity, _), records in source.records_by_entity_event.items():
        direct.setdefault(entity.value, set()).add(entity)
        records_by_entity.setdefault(entity, []).extend(records)
    limit = max((event.index for event in ledger.events if event.source.document == "prompt"), default=-1)
    names = {declaration.tool.name for declaration in declarations}
    for cid, claim in claims.items():
        row = rows.get(cid)
        if row is None:
            continue
        if (row.disposition, row.kind) != (claim.disposition, claim.kind):
            errors.append("SPAN_DISPOSITION_OR_KIND_CHANGED:" + cid)
        if row.scope != "CONDITIONAL_EXACT_RESULT_FIELD_AGREEMENT_NOT_CURRENT_STATE_COMPLETION_CAUSALITY_OR_CORE_VERDICT":
            errors.append("FIELD_PROOF_SCOPE_CHANGED:" + cid)
        allowed = (claim.disposition is Disposition.VERIFIABLE_TYPED and claim.kind is ClaimKind.ATTRIBUTION
            and claim.modality in {"ASSERTED", "REPORTED"} and claim.polarity == "POSITIVE" and not claim.unknown_fields
            and bool(claim.source_refs) and "UNKNOWN" not in claim.source_refs and claim.time_anchor == "PAST"
            and claim.actor in {"tool", "TOOL", *names}
            and all(ref.upper() == "TOOL" or ref.removeprefix("TOOL:") in names for ref in claim.source_refs))
        if not allowed:
            if row.meanings or row.bindings or row.value is not Truth.UNKNOWN:
                errors.append("UNSUPPORTED_CLAIM_USED_AS_FIELD_FACT:" + cid)
            continue
        literals = target_literals(response, claim)
        if row.literals != literals:
            errors.append("TARGET_LITERAL_SOURCE_OR_VALUE_CHANGED:" + cid)
        literals_by_id = {literal.literal_id: literal for literal in literals}
        text = response[claim.span.start:claim.span.end]
        refs = tuple(dict.fromkeys(ref for ref in claim.entity_refs
            if ref and re.search(r"(?<!\w)" + re.escape(ref) + r"(?!\w)", text)))
        entities = set()
        if limit >= 0:
            for ref in refs:
                entities.update(source.resolve(ref, before_index=limit).entities)
                entities.update(entity for entity in direct.get(ref, ())
                    if any(record.index <= limit for record in records_by_entity[entity]))
        allowed_names = names if any(ref.upper() == "TOOL" for ref in claim.source_refs) else {
            ref.removeprefix("TOOL:") for ref in claim.source_refs}
        records = tuple(record for entity in entities for record in records_by_entity[entity]
            if record.index <= limit and ledger.events[record.index].tool.name in allowed_names)
        groups = {(record.entity, record.event_id, record.index) for record in records}
        paths = {path for record in records for path in field_paths(decode_json(record.record_json)[0])}
        complete = bool(groups) and bool(refs) and ledger.history_complete and bool(ledger.completeness_basis)
        complete = complete and not any(position <= limit for position, _ in source.source_issues)
        if row.candidate_set_complete != complete or row.searched_record_count != len(records):
            errors.append("CANDIDATE_COMPLETENESS_OR_COUNT_CHANGED:" + cid)
        meanings = {meaning.meaning_id: meaning for meaning in row.meanings}
        if len(meanings) != len(row.meanings):
            errors.append("MEANING_DROPPED_OR_DUPLICATED:" + cid)
        expected = set()
        for mid, meaning in meanings.items():
            literal = literals_by_id.get(meaning.literal_id)
            if literal is None or meaning.field_path not in paths:
                errors.append("MEANING_NOT_SOURCE_GROUNDED:" + cid)
                continue
            expected.update((mid, event_id, ScopedFieldQuery(entity, position, meaning.field_path, literal.expected_json))
                for entity, event_id, position in groups)
        actual = [(binding.meaning_id, binding.event_id, binding.query) for binding in row.bindings]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            errors.append("BINDING_ALTERNATIVE_DROPPED_OR_INVENTED:" + cid)
        for binding in row.bindings:
            if binding.proof != prove_scoped_field(binding.query, source):
                errors.append("PRIMITIVE_SOURCE_RECHECK_FAILED:" + cid)
        values = {binding.proof.value for binding in row.bindings}
        agreement = next(iter(values)) if complete and not row.unresolved_terms and len(values) == 1 else Truth.UNKNOWN
        if row.value is not agreement:
            errors.append("CONDITIONAL_AGREEMENT_RECHECK_FAILED:" + cid)
    return FieldEvidenceCheck(not errors, tuple(dict.fromkeys(errors)))


def make_envelope_field_receipt(envelope, declarations, graph, evidence):
    checked = check_envelope_field_evidence(envelope, declarations, graph, evidence)
    if not checked.valid:
        raise ValueError("field evidence must independently validate before receipt issuance")
    return EnvelopeFieldReceipt("guardian-vnext-envelope-field-evidence-v4", source_hash(envelope, declarations, graph),
        digest(asdict(evidence)), ASSUMPTIONS)


def check_envelope_field_receipt(receipt, envelope, declarations, graph, evidence):
    errors = list(check_envelope_field_evidence(envelope, declarations, graph, evidence).errors)
    if (not isinstance(receipt, EnvelopeFieldReceipt) or receipt.version != "guardian-vnext-envelope-field-evidence-v4"
            or receipt.assumptions != ASSUMPTIONS or receipt.source_sha256 != source_hash(envelope, declarations, graph)
            or receipt.evidence_sha256 != digest(asdict(evidence))):
        errors.append("RECEIPT_SOURCE_HASH_OR_ASSUMPTIONS_CHANGED")
    return FieldEvidenceCheck(not errors, tuple(dict.fromkeys(errors)))

"""Independent source/coverage recheck for scoped Claim Graph field evidence.

No semantic backend, binding builder, solver or Core adapter is called. This
receipt certifies conditional primitive evidence, not NL meaning or Core safety.
"""

from dataclasses import asdict, dataclass
import re

from guardian_truth.cycle2.claims import response_spans
from guardian_truth.parsing import decode_json
from .claim_field_bindings_v3 import field_paths, target_literals
from .identity_aliases_v2 import IdentityAliasIndex
from .integrity import digest
from .ledger import EvidenceLedger
from .normalize_source_v3 import normalize_source
from .scoped_result_evidence_v2 import ScopedFieldQuery, prove_scoped_field
from .types import ClaimKind, Disposition, Reason, Truth


@dataclass(frozen=True)
class FieldEvidenceCheck:
    valid: bool
    errors: tuple[str, ...]


@dataclass(frozen=True)
class FieldEvidenceReceipt:
    version: str
    source_sha256: str
    evidence_sha256: str
    assumptions: tuple[tuple[str, str], ...]


ASSUMPTIONS = (
    ('MEANINGS', 'conditional on all retained source-field/target-literal mappings; unrestricted NL completeness not asserted'),
    ('EVIDENCE', 'exact original TOOL-result records only, all compatible identities/results retained'),
    ('SCOPE', 'field-attribution evidence only; no current-state/completion/causality/Core safety verdict'),
)


def source_hash(prompt, response, metadata, declarations, graph, history_complete, completeness_basis, before_index=None):
    return digest({'prompt': prompt, 'response': response, 'metadata': [asdict(item) for item in metadata],
        'declarations': [asdict(item) for item in declarations], 'graph': asdict(graph),
        'history_complete': history_complete, 'completeness_basis': completeness_basis, 'before_index': before_index})


def check_field_evidence(prompt, response, metadata, declarations, graph, evidence, *,
        history_complete=False, completeness_basis=None, before_index=None):
    errors = []
    if graph.response_sha256 != digest(response) or evidence.response_sha256 != graph.response_sha256:
        errors.append('TARGET_SOURCE_HASH_MISMATCH')
    if evidence.identity_declarations_sha256 != digest([asdict(item) for item in declarations]):
        errors.append('IDENTITY_DECLARATION_HASH_MISMATCH')
    spans = {item['span_id']: (item['start'], item['end']) for item in response_spans(response)}
    claims = {claim.claim_id: claim for claim in graph.claims}
    rows = {row.claim_id: row for row in evidence.claims}
    if (len(claims) != len(graph.claims) or set(claims) != set(spans)
            or any(claim.span.document != 'response' or (claim.span.start, claim.span.end) != spans.get(claim.claim_id)
                for claim in graph.claims)):
        errors.append('DETERMINISTIC_SPAN_INVENTORY_MISMATCH')
    if len(rows) != len(evidence.claims) or set(rows) != set(claims):
        errors.append('CLAIM_DROPPED_OR_DUPLICATED')
    if evidence.failures != tuple((row.claim_id, reason) for row in evidence.claims for reason in row.reasons
            if reason in {Reason.TRANSPORT_ERROR, Reason.SCHEMA_ERROR}):
        errors.append('COMPONENT_FAILURE_AUDIT_CHANGED')
    ledger = EvidenceLedger.from_events(normalize_source(prompt, response, tool_identities=metadata),
        history_complete=history_complete, completeness_basis=completeness_basis)
    source = IdentityAliasIndex(ledger, declarations)
    # Independent record lookup tables, built once, not an all-history scan
    # for every claim. No binding-builder result is trusted as this index.
    direct_entities, entity_records = {}, {}
    for (entity, _), records in source.records_by_entity_event.items():
        direct_entities.setdefault(entity.value, set()).add(entity)
        entity_records.setdefault(entity, []).extend(records)
    limit = len(ledger.events) - 1 if before_index is None else before_index
    if not ledger.events and not claims:
        return FieldEvidenceCheck(not errors, tuple(dict.fromkeys(errors)))
    if type(limit) is not int or not 0 <= limit < len(ledger.events):
        errors.append('SOURCE_TIME_UNBOUND')
        return FieldEvidenceCheck(False, tuple(dict.fromkeys(errors)))
    limit = min(limit, max((event.index for event in ledger.events if event.source.document == 'prompt'), default=-1))
    for cid, claim in claims.items():
        row = rows.get(cid)
        if row is None:
            continue
        if (row.disposition, row.kind) != (claim.disposition, claim.kind):
            errors.append('SPAN_DISPOSITION_OR_KIND_CHANGED:' + cid)
        if row.scope != 'CONDITIONAL_EXACT_RESULT_FIELD_AGREEMENT_NOT_CURRENT_STATE_COMPLETION_CAUSALITY_OR_CORE_VERDICT':
            errors.append('FIELD_PROOF_SCOPE_CHANGED:' + cid)
        declared_names = {declaration.tool.name for declaration in declarations}
        allowed = (claim.disposition is Disposition.VERIFIABLE_TYPED and claim.kind is ClaimKind.ATTRIBUTION
            and claim.modality in {'ASSERTED', 'REPORTED'} and claim.polarity == 'POSITIVE'
            and not claim.unknown_fields and bool(claim.source_refs) and 'UNKNOWN' not in claim.source_refs
            and claim.actor in {'tool', 'TOOL', *declared_names}
            and all(ref.upper() == 'TOOL' or ref.removeprefix('TOOL:') in declared_names for ref in claim.source_refs))
        if not allowed:
            if row.meanings or row.bindings or row.value is not Truth.UNKNOWN:
                errors.append('UNSUPPORTED_CLAIM_USED_AS_FIELD_FACT:' + cid)
            continue
        literals = target_literals(response, claim)
        if row.literals != literals:
            errors.append('TARGET_LITERAL_SOURCE_OR_VALUE_CHANGED:' + cid)
        literal_by_id = {literal.literal_id: literal for literal in literals}
        text = response[claim.span.start:claim.span.end]
        refs = tuple(dict.fromkeys(ref for ref in claim.entity_refs
            if ref and re.search(r'(?<!\w)' + re.escape(ref) + r'(?!\w)', text)))
        entities = set()
        if limit >= 0:
            for ref in refs:
                entities.update(source.resolve(ref, before_index=limit).entities)
                # Direct stable IDs do not depend on alias equality.
                entities.update(entity for entity in direct_entities.get(ref, ())
                    if any(record.index <= limit for record in entity_records[entity]))
        generic_tool = any(ref.upper() == 'TOOL' for ref in claim.source_refs)
        allowed_names = declared_names if generic_tool else {ref.removeprefix('TOOL:') for ref in claim.source_refs}
        records = tuple(record for entity in entities for record in entity_records[entity]
            if record.index <= limit and ledger.events[record.index].tool.name in allowed_names)
        groups = {(record.entity, record.event_id, record.index) for record in records}
        paths = {path for record in records for path in field_paths(decode_json(record.record_json)[0])}
        complete = bool(groups) and bool(refs) and history_complete and bool(completeness_basis)
        complete = complete and not any(position <= limit for position, _ in source.source_issues)
        if row.candidate_set_complete != complete or row.searched_record_count != len(records):
            errors.append('CANDIDATE_COMPLETENESS_OR_COUNT_CHANGED:' + cid)
        meanings = {meaning.meaning_id: meaning for meaning in row.meanings}
        if len(meanings) != len(row.meanings):
            errors.append('MEANING_DROPPED_OR_DUPLICATED:' + cid)
        expected = set()
        for mid, meaning in meanings.items():
            literal = literal_by_id.get(meaning.literal_id)
            if literal is None or meaning.field_path not in paths:
                errors.append('MEANING_NOT_SOURCE_GROUNDED:' + cid)
                continue
            expected.update((mid, event_id, ScopedFieldQuery(entity, position, meaning.field_path, literal.expected_json))
                for entity, event_id, position in groups)
        actual = [(binding.meaning_id, binding.event_id, binding.query) for binding in row.bindings]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            errors.append('BINDING_ALTERNATIVE_DROPPED_OR_INVENTED:' + cid)
        for binding in row.bindings:
            if binding.proof != prove_scoped_field(binding.query, source):
                errors.append('PRIMITIVE_SOURCE_RECHECK_FAILED:' + cid)
        values = {binding.proof.value for binding in row.bindings}
        agreement = next(iter(values)) if complete and not row.unresolved_terms and len(values) == 1 else Truth.UNKNOWN
        if row.value is not agreement:
            errors.append('CONDITIONAL_AGREEMENT_RECHECK_FAILED:' + cid)
    return FieldEvidenceCheck(not errors, tuple(dict.fromkeys(errors)))


def make_field_receipt(prompt, response, metadata, declarations, graph, evidence, *,
        history_complete=False, completeness_basis=None, before_index=None):
    checked = check_field_evidence(prompt, response, metadata, declarations, graph, evidence,
        history_complete=history_complete, completeness_basis=completeness_basis, before_index=before_index)
    if not checked.valid:
        raise ValueError('field evidence must independently validate before a receipt is issued')
    return FieldEvidenceReceipt('guardian-vnext-field-evidence-v3',
        source_hash(prompt, response, metadata, declarations, graph, history_complete, completeness_basis, before_index),
        digest(asdict(evidence)), ASSUMPTIONS)


def check_field_receipt(receipt, prompt, response, metadata, declarations, graph, evidence, *,
        history_complete=False, completeness_basis=None, before_index=None):
    errors = list(check_field_evidence(prompt, response, metadata, declarations, graph, evidence,
        history_complete=history_complete, completeness_basis=completeness_basis, before_index=before_index).errors)
    if (receipt.version != 'guardian-vnext-field-evidence-v3' or receipt.assumptions != ASSUMPTIONS
            or receipt.source_sha256 != source_hash(prompt, response, metadata, declarations, graph, history_complete, completeness_basis, before_index)
            or receipt.evidence_sha256 != digest(asdict(evidence))):
        errors.append('RECEIPT_SOURCE_HASH_OR_ASSUMPTIONS_CHANGED')
    return FieldEvidenceCheck(not errors, tuple(dict.fromkeys(errors)))

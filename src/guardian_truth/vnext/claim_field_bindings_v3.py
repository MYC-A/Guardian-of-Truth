"""Typed Claim Graph -> indexed, record-scoped result-field proof candidates.

The extra narrow pass selects source-owned field paths and deterministic target
literal IDs, never offsets or facts. Every compatible identity/result binding is
retained. These are conditional evidence propositions, not a whole-Core verdict.
"""

from dataclasses import asdict, dataclass
import json
import re

from guardian_truth.parsing import decode_json
from .identity_aliases_v2 import IdentityAliasIndex
from .integrity import canonical, digest
from .schema_diagnostics import schema_issues
from .scoped_result_evidence_v2 import ScopedFieldQuery, prove_scoped_field
from .types import ClaimKind, Disposition, Reason, Span, Truth


@dataclass(frozen=True)
class TargetLiteral:
    literal_id: str
    source: Span
    expected_json: str


@dataclass(frozen=True)
class FieldMeaning:
    meaning_id: str
    literal_id: str
    field_path: tuple[str, ...]


@dataclass(frozen=True)
class FieldBinding:
    meaning_id: str
    event_id: str
    query: ScopedFieldQuery
    proof: object


@dataclass(frozen=True)
class ClaimFieldEvidence:
    claim_id: str
    disposition: Disposition
    kind: ClaimKind | None
    literals: tuple[TargetLiteral, ...]
    meanings: tuple[FieldMeaning, ...]
    bindings: tuple[FieldBinding, ...]
    candidate_set_complete: bool
    searched_record_count: int
    reasons: tuple[Reason, ...]
    value: Truth
    unresolved_terms: tuple[str, ...] = ()
    scope: str = 'CONDITIONAL_EXACT_RESULT_FIELD_AGREEMENT_NOT_CURRENT_STATE_COMPLETION_CAUSALITY_OR_CORE_VERDICT'


@dataclass(frozen=True)
class GraphFieldEvidence:
    response_sha256: str
    claims: tuple[ClaimFieldEvidence, ...]
    failures: tuple[tuple[str, Reason], ...]
    identity_declarations_sha256: str


def target_literals(response, claim):
    """Code owns all offsets. Strict JSON literals; IDs are not numeric values.

    JSON strings/arrays/objects consume their complete lexical range, so a
    quoted string "42" does not secretly create a numeric 42 interpretation.
    Natural-language words are deliberately not coerced into scalar values.
    """
    text = response[claim.span.start:claim.span.end]
    decoder = json.JSONDecoder(parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
    literals, consumed = [], 0
    for start, character in enumerate(text):
        if start < consumed or character not in '-0123456789[{"tfn':
            continue
        if start and (text[start - 1].isalnum() or text[start - 1] in '_-"'):
            continue
        try:
            value, length = decoder.raw_decode(text[start:])
            encoded = canonical(value).decode('utf-8')
        except (ValueError, TypeError, RecursionError):
            continue
        end = start + length
        if end < len(text) and (text[end].isalnum() or text[end] in '_-.'):
            # A sentence-final '.' is punctuation, not an ID/number suffix.
            if text[end] != '.' or end + 1 < len(text) and text[end + 1].isalnum():
                continue
        literals.append(TargetLiteral(f'{claim.claim_id}:literal:{len(literals)}',
            Span('response', claim.span.start + start, claim.span.start + end), encoded))
        consumed = end
    return tuple(literals)


def field_paths(record, prefix=()):
    """Actual record fields only; array contents are not flattened across IDs."""
    if not isinstance(record, dict):
        return ()
    paths = []
    for key, value in record.items():
        if not isinstance(key, str) or not key:
            continue
        path = (*prefix, key)
        paths.append(path)
        if isinstance(value, dict):
            paths.extend(field_paths(value, path))
    return tuple(paths)


class ClaimFieldIndex:
    def __init__(self, source):
        if not isinstance(source, IdentityAliasIndex):
            raise TypeError('source-owned record/alias index required')
        self.source = source
        by_id, by_entity = {}, {}
        for (entity, event_id), records in source.records_by_entity_event.items():
            by_id.setdefault(entity.value, set()).add(entity)
            by_entity.setdefault(entity, []).extend(records)
        self.by_id = {value: tuple(sorted(entities, key=lambda entity: (entity.namespace, entity.key, entity.value)))
            for value, entities in by_id.items()}
        self.by_entity = {entity: tuple(records) for entity, records in by_entity.items()}

    def candidates(self, claim, response, before_index):
        text = response[claim.span.start:claim.span.end]
        # Serialized result-looking text in the target cannot mutate aliases or
        # become evidence. The trusted history prefix ends before the target.
        before_index = min(before_index, max((event.index for event in self.source.ledger.events
            if event.source.document == 'prompt'), default=-1))
        if before_index < 0:
            return (), (), False, 0, 0
        declared_names = {declaration.tool.name for declaration in self.source.declarations}
        generic_tool = any(ref.upper() == 'TOOL' for ref in claim.source_refs)
        allowed_names = declared_names if generic_tool else {ref.removeprefix('TOOL:')
            for ref in claim.source_refs if ref.removeprefix('TOOL:') in declared_names}
        refs = tuple(dict.fromkeys(ref for ref in claim.entity_refs
            if ref and re.search(r'(?<!\w)' + re.escape(ref) + r'(?!\w)', text)))
        entities, records, complete = set(), [], self.source.ledger.history_complete and bool(self.source.ledger.completeness_basis)
        issues = [code for position, code in self.source.source_issues if position <= before_index]
        complete = complete and not issues and bool(refs)
        for ref in refs:
            alias = self.source.resolve(ref, before_index=before_index)
            entities.update(alias.entities)
            entities.update(entity for entity in self.by_id.get(ref, ())
                if any(record.index <= before_index for record in self.by_entity[entity]))
        for entity in sorted(entities, key=lambda entity: (entity.namespace, entity.key, entity.value)):
            records.extend(record for record in self.by_entity[entity] if record.index <= before_index
                and self.source.ledger.events[record.index].tool.name in allowed_names)
        # Same-ID duplicate rows are preserved for BOTH; lookup groups by event.
        groups = tuple(sorted({(record.entity, record.event_id, record.index) for record in records},
            key=lambda item: (item[2], item[0].namespace, item[0].key, item[0].value)))
        paths = set()
        for record in records:
            value, valid = decode_json(record.record_json)
            if valid:
                paths.update(field_paths(value))
        return groups, tuple(sorted(paths)), complete and bool(groups), len(records), len({record.entity for record in records})


def _unknown(claim, literals=(), reason=Reason.CLAIM_UNTYPED, *, complete=False, searched=0):
    return ClaimFieldEvidence(claim.claim_id, claim.disposition, claim.kind, literals, (), (), complete, searched,
        () if claim.disposition is Disposition.NON_VERIFIABLE else (reason,), Truth.UNKNOWN)


def interpret_claim_result_field(response, claim, index, backend, *, before_index=None):
    source = index.source
    before_index = len(source.ledger.events) - 1 if before_index is None else before_index
    if (claim.span.document != 'response' or claim.span.end > len(response)
            or type(before_index) is not int or not 0 <= before_index < len(source.ledger.events)):
        return _unknown(claim, reason=Reason.TIME_UNBOUND)
    # Result-attribution is intentionally distinct from current state/action.
    if (claim.disposition is not Disposition.VERIFIABLE_TYPED or claim.kind is not ClaimKind.ATTRIBUTION
            or claim.modality not in {'ASSERTED', 'REPORTED'} or claim.polarity != 'POSITIVE'
            or claim.unknown_fields or not claim.source_refs or 'UNKNOWN' in claim.source_refs):
        return _unknown(claim, reason=Reason.CAUSALITY_UNPROVED if claim.kind is ClaimKind.CAUSAL_ATTRIBUTION else Reason.CLAIM_UNTYPED)
    declared_names = {declaration.tool.name for declaration in source.declarations}
    if (claim.actor not in {'tool', 'TOOL', *declared_names}
            or any(ref.upper() != 'TOOL' and ref.removeprefix('TOOL:') not in declared_names for ref in claim.source_refs)):
        return _unknown(claim, reason=Reason.SOURCE_UNBOUND)
    if claim.time_anchor != 'PAST':
        # This pass does not ground dates, relative times, freshness or the
        # existence of a result at the current target moment.
        return _unknown(claim, reason=Reason.TIME_UNBOUND)
    literals = target_literals(response, claim)
    groups, paths, complete, searched, entity_count = index.candidates(claim, response, before_index)
    if not groups:
        return _unknown(claim, literals, Reason.ENTITY_UNBOUND, searched=searched)
    if not literals or not paths:
        return _unknown(claim, literals, complete=complete, searched=searched)
    path_ids = {f'field:{ordinal}': path for ordinal, path in enumerate(paths)}
    literal_ids = {literal.literal_id: literal for literal in literals}
    interpretation = {'type': 'object', 'additionalProperties': False, 'required': ['literal_id', 'field_id'],
        'properties': {'literal_id': {'type': 'string', 'enum': list(literal_ids)},
            'field_id': {'type': 'string', 'enum': list(path_ids)}}}
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['interpretations', 'unresolved_terms'],
        'properties': {'interpretations': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'uniqueItems': True, 'items': interpretation},
            'unresolved_terms': {'type': 'array', 'uniqueItems': True, 'items': {'type': 'string'}}}}
    payload = {'claim': {key: value for key, value in asdict(claim).items() if key != 'span'},
        'span_text': response[claim.span.start:claim.span.end],
        'target_literals': [{'literal_id': literal.literal_id, 'expected_json': literal.expected_json,
            'text': response[literal.source.start:literal.source.end]} for literal in literals],
        'source_fields': [{'field_id': key, 'path': list(path)} for key, path in path_ids.items()],
        'instructions': 'Interpret only the stated TOOL-result field attribution. Select deterministic target literal IDs and actual source field IDs, not offsets or a verdict. Preserve plausible different readings. All compatible source entities/results will be checked, never select a convenient record. Field catalog is not NL closure. Undefined or nonliteral value semantics remain unresolved.'}
    proposal = backend.propose('claim_result_field_meanings_v3', payload, schema)
    if proposal.transport_status != 'SUCCESS':
        return _unknown(claim, literals, Reason.TRANSPORT_ERROR, complete=complete, searched=searched)
    if proposal.schema_status != 'VALID' or schema_issues(proposal.value, schema):
        return _unknown(claim, literals, Reason.SCHEMA_ERROR, complete=complete, searched=searched)
    meanings, bindings = [], []
    for ordinal, item in enumerate(proposal.value['interpretations']):
        meaning = FieldMeaning(f'{claim.claim_id}:field-meaning:{ordinal}', item['literal_id'], path_ids[item['field_id']])
        meanings.append(meaning)
        for entity, event_id, position in groups:
            query = ScopedFieldQuery(entity, position, meaning.field_path, literal_ids[meaning.literal_id].expected_json)
            bindings.append(FieldBinding(meaning.meaning_id, event_id, query, prove_scoped_field(query, source)))
    reasons = [reason for binding in bindings for reason in binding.proof.reasons]
    if entity_count > 1:
        reasons.append(Reason.ENTITY_AMBIGUOUS)
    if not complete:
        reasons.append(Reason.EVIDENCE_INCOMPLETE)
    if proposal.value['unresolved_terms']:
        reasons.append(Reason.CLAIM_UNTYPED)
    values = {binding.proof.value for binding in bindings}
    value = next(iter(values)) if complete and not proposal.value['unresolved_terms'] and len(values) == 1 else Truth.UNKNOWN
    return ClaimFieldEvidence(claim.claim_id, claim.disposition, claim.kind, literals, tuple(meanings), tuple(bindings), complete, searched,
        tuple(dict.fromkeys(reasons)), value, tuple(proposal.value['unresolved_terms']))


def interpret_graph_result_fields(response, graph, source, backend, *, before_index=None):
    if graph.response_sha256 != digest(response):
        raise ValueError('Claim Graph must belong to the exact target response')
    index = ClaimFieldIndex(source)
    claims = tuple(interpret_claim_result_field(response, claim, index, backend, before_index=before_index)
        for claim in graph.claims)
    failures = tuple((claim.claim_id, reason) for claim in claims for reason in claim.reasons
        if reason in {Reason.TRANSPORT_ERROR, Reason.SCHEMA_ERROR})
    return GraphFieldEvidence(graph.response_sha256, claims, failures,
        digest([asdict(declaration) for declaration in source.declarations]))

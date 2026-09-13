"""Record-scoped result-field evidence, not current state or causal attribution."""

from dataclasses import dataclass

from guardian_truth.parsing import decode_json
from .integrity import canonical
from .schema_diagnostics import json_equal
from .types import EntityRef, Reason, Truth


@dataclass(frozen=True)
class ScopedFieldQuery:
    entity: EntityRef
    event_index: int
    field_path: tuple[str, ...]
    expected_json: str

    def __post_init__(self):
        value, valid = decode_json(self.expected_json)
        if not valid or canonical(value).decode('utf-8') != self.expected_json:
            raise ValueError('canonical finite expected JSON required')
        if type(self.field_path) is not tuple or not self.field_path or any(not isinstance(part, str) or not part for part in self.field_path):
            raise ValueError('explicit immutable source field path required')
        if not isinstance(self.entity, EntityRef) or type(self.event_index) is not int:
            raise ValueError('scoped identity and exact source time required')


@dataclass(frozen=True)
class ScopedFieldProof:
    query: ScopedFieldQuery
    value: Truth
    supporting_paths: tuple[tuple[str, ...], ...]
    refuting_paths: tuple[tuple[str, ...], ...]
    reasons: tuple[Reason, ...] = ()
    searched_record_count: int = 0
    scope: str = 'EXACT_TOOL_RESULT_FIELD_ONLY_NOT_CURRENT_STATE_COMPLETION_OR_CAUSALITY'


def prove_scoped_field(query, index):
    if not 0 <= query.event_index < len(index.ledger.events):
        return ScopedFieldProof(query, Truth.UNKNOWN, (), (), (Reason.TIME_UNBOUND,))
    event = index.ledger.events[query.event_index]
    declarations = [item for item in index.declarations if item.tool == event.tool
        and item.namespace == query.entity.namespace and item.id_field == query.entity.key]
    if event.kind != 'result' or event.actor != 'tool' or event.payload_json is None or event.pairing_issue or len(declarations) != 1:
        return ScopedFieldProof(query, Truth.UNKNOWN, (), (), (Reason.SOURCE_UNBOUND,))
    expected, _ = decode_json(query.expected_json)
    support, refute = [], []
    incomplete = event.event_id in index.malformed_record_event_ids
    records = index.records_by_entity_event.get((query.entity, event.event_id), ())
    for observation in records:
        record, _ = decode_json(observation.record_json)
        record_path = observation.record_path
        value = record
        for part in query.field_path:
            if not isinstance(value, dict) or part not in value:
                incomplete = True
                break
            value = value[part]
        else:
            (support if json_equal(value, expected) else refute).append((*record_path, *query.field_path))
    value = Truth.BOTH if support and refute else Truth.TRUE if support else Truth.FALSE if refute else Truth.UNKNOWN
    # Malformed records could contain another matching identity/value. A partial
    # result cannot turn missing data into a conclusive negative.
    if incomplete and value is not Truth.BOTH:
        value = Truth.UNKNOWN
    reasons = (Reason.EVIDENCE_INCOMPLETE,) if value is Truth.UNKNOWN else ()
    return ScopedFieldProof(query, value, tuple(support), tuple(refute), reasons, len(records))


def query_alias_field(index, alias, event_index, field_path, expected_json, *, namespace=None):
    candidates = index.resolve(alias, before_index=event_index, namespace=namespace)
    proofs = tuple(prove_scoped_field(ScopedFieldQuery(entity, event_index, field_path, expected_json), index)
        for entity in candidates.entities)
    values = {proof.value for proof in proofs}
    value = next(iter(values)) if candidates.searched_source_complete and len(values) == 1 else Truth.UNKNOWN
    return {'value': value, 'proofs': proofs, 'candidates': candidates,
        'scope': 'all observed source-owned alias bindings; not unrestricted identity closure or Core verdict'}

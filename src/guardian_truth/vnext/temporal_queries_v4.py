"""Indexed typed temporal proofs. Application contracts, never LLM guesses.

These are source-scoped primitive results, NOT whole-Core ERROR/NO_ERROR verdicts.
Snapshots are recorded observations; completion/causation require actual T1.
"""

from dataclasses import asdict, dataclass

from guardian_truth.parsing import decode_json
from .identity_aliases_v2 import IdentityAliasIndex, IdentityDeclaration
from .integrity import canonical, digest
from .ledger import LedgerIndex
from .scoped_result_evidence_v2 import ScopedFieldQuery, prove_scoped_field
from .tools import ContractRegistry, FieldCondition, conditions_hold, evaluate_t1, read_path
from .types import EffectStatus, EntityRef, Reason, ToolIdentity, Truth


@dataclass(frozen=True)
class SnapshotDeclaration:
    identity: IdentityDeclaration
    complete_conditions: tuple[FieldCondition, ...]

    def __post_init__(self):
        if not isinstance(self.identity, IdentityDeclaration) or type(self.complete_conditions) is not tuple:
            raise ValueError("source-owned immutable snapshot declaration required")
        if any(condition.source != "result" for condition in self.complete_conditions):
            raise ValueError("snapshot scope conditions must inspect the actual result")


@dataclass(frozen=True)
class MethodDeclaration:
    identity: ToolIdentity
    namespace: str
    id_field: str
    argument_entity_path: tuple[str, ...]
    effect_predicate: str
    authority_source: str
    effect_value_json: str

    def __post_init__(self):
        if not isinstance(self.identity, ToolIdentity) or not self.namespace or not self.id_field or not self.effect_predicate or not self.authority_source:
            raise ValueError("authoritative method/resource mapping required")
        if type(self.argument_entity_path) is not tuple or not self.argument_entity_path or any(not isinstance(part, str) or not part for part in self.argument_entity_path):
            raise ValueError("immutable source-owned entity argument mapping required")
        value, valid = decode_json(self.effect_value_json)
        if not valid or canonical(value).decode() != self.effect_value_json:
            raise ValueError("exact canonical method effect value required")


@dataclass(frozen=True)
class TemporalQuery:
    kind: str
    entity_mode: str
    entity_value: str
    namespace: str
    id_field: str
    expected_json: str
    field_path: tuple[str, ...] = ()
    actor: str = "assistant"
    method_identities: tuple[ToolIdentity, ...] = ()
    argument_entity_path: tuple[str, ...] = ()
    effect_predicate: str | None = None
    call_event_id: str | None = None
    before_index: int | None = None
    method_effect_value_json: str | None = None

    def __post_init__(self):
        if self.kind not in {"FIELD_AT_LAST_READ", "ALIAS_HISTORY", "METHOD_HISTORY", "METHOD_COMPLETION_COUNT", "CAUSE_OF_METHOD"}:
            raise ValueError("unsupported typed temporal query")
        if self.entity_mode not in {"id", "name"} or any(not isinstance(value, str) or not value for value in
                (self.entity_value, self.namespace, self.id_field)):
            raise ValueError("explicit entity selector and source namespace required")
        value, valid = decode_json(self.expected_json)
        if not valid or canonical(value).decode() != self.expected_json:
            raise ValueError("canonical finite typed expected JSON required")
        if self.before_index is not None and (type(self.before_index) is not int or self.before_index < 0):
            raise ValueError("nonnegative source boundary required")
        if any(type(items) is not tuple for items in (self.field_path, self.method_identities, self.argument_entity_path)):
            raise ValueError("immutable query selectors required")
        if self.kind == "FIELD_AT_LAST_READ" and (not self.field_path or any(not isinstance(part, str) or not part for part in self.field_path)):
            raise ValueError("exact field path required")
        if self.kind == "ALIAS_HISTORY" and not isinstance(value, str):
            raise ValueError("alias-history expected value is the observed alias string")
        if self.kind in {"METHOD_HISTORY", "CAUSE_OF_METHOD"} and type(value) is not bool:
            raise ValueError("Boolean method occurrence proposition required")
        if self.kind == "METHOD_COMPLETION_COUNT" and (type(value) is not int or value < 0):
            raise ValueError("nonnegative exact mutation count required")
        if self.kind in {"METHOD_HISTORY", "METHOD_COMPLETION_COUNT", "CAUSE_OF_METHOD"}:
            if self.actor not in {"assistant", "user"} or not self.method_identities or not self.argument_entity_path or not self.effect_predicate:
                raise ValueError("source-owned method identities, actor, entity argument and effect predicate required")
            if len(set(self.method_identities)) != len(self.method_identities) or any(not isinstance(item, ToolIdentity) for item in self.method_identities):
                raise ValueError("unique exact method identities required")
            effect_value, effect_valid = decode_json(self.method_effect_value_json or "")
            if not effect_valid or canonical(effect_value).decode() != self.method_effect_value_json:
                raise ValueError("canonical source-grounded method effect value required")
        if self.kind == "CAUSE_OF_METHOD" and not self.call_event_id:
            raise ValueError("specific source call event required for causation")


@dataclass(frozen=True)
class MethodOccurrence:
    call_event_id: str
    result_event_ids: tuple[str, ...]
    value: Truth
    effect_ids: tuple[str, ...]
    contract_sha256: str | None
    reasons: tuple[Reason, ...] = ()


@dataclass(frozen=True)
class TemporalBinding:
    entity: EntityRef
    value: Truth
    supporting_event_ids: tuple[str, ...] = ()
    refuting_event_ids: tuple[str, ...] = ()
    unknown_event_ids: tuple[str, ...] = ()
    occurrences: tuple[MethodOccurrence, ...] = ()
    searched_record_count: int = 0


@dataclass(frozen=True)
class TemporalEvidence:
    query: TemporalQuery
    value: Truth
    bindings: tuple[TemporalBinding, ...]
    candidate_set_complete: bool
    history_complete: bool
    snapshot_event_id: str | None
    searched_event_ids: tuple[str, ...]
    reasons: tuple[Reason, ...]
    scope: str = "SOURCE_TYPED_TEMPORAL_PRIMITIVE_NOT_CORE_VERDICT_OR_UNRESTRICTED_NL_CLOSURE"


def consensus(values):
    distinct = set(values)
    return next(iter(distinct)) if len(distinct) == 1 else Truth.UNKNOWN


def invert(value):
    return {Truth.TRUE: Truth.FALSE, Truth.FALSE: Truth.TRUE, Truth.UNKNOWN: Truth.UNKNOWN, Truth.BOTH: Truth.BOTH}[value]


class TemporalQueryIndex:
    """Build source-record and method indexes once; query all compatible evidence."""

    def __init__(self, ledger, declarations, registry, methods=()):
        self.ledger, self.registry = ledger, registry
        self.declarations = tuple(declarations)
        self.methods = tuple(methods)
        if any(not isinstance(item, MethodDeclaration) for item in self.methods) or len({item.identity for item in self.methods}) != len(self.methods):
            raise ValueError("unique source-owned method/resource mappings required")
        if not isinstance(registry, ContractRegistry) or any(not isinstance(item, SnapshotDeclaration) for item in self.declarations):
            raise ValueError("application-supplied snapshot and T1 contracts required")
        self.by_tool = {item.identity.tool: item for item in self.declarations}
        if len(self.by_tool) != len(self.declarations):
            raise ValueError("unique snapshot identity declarations required")
        self.records = IdentityAliasIndex(ledger, tuple(item.identity for item in self.declarations))
        self.events = LedgerIndex(ledger)
        snapshot_names = {tool.name for tool in self.by_tool}
        self.snapshot_events = tuple(event for event in ledger.events if event.kind == "result" and event.tool and event.tool.name in snapshot_names)
        direct = {}
        for (entity, _), records in self.records.records_by_entity_event.items():
            direct.setdefault(entity, []).extend(records)
        self.records_by_entity = {entity: tuple(records) for entity, records in direct.items()}

    def evaluate(self, query):
        limit = len(self.ledger.events) - 1 if query.before_index is None else query.before_index
        if not 0 <= limit < len(self.ledger.events):
            return TemporalEvidence(query, Truth.UNKNOWN, (), False, False, None, (), (Reason.TIME_UNBOUND,))
        snapshots = tuple(event for event in self.snapshot_events if event.index <= limit)
        latest = snapshots[-1] if snapshots else None
        latest_spec = self.by_tool.get(latest.tool) if latest else None
        snapshot_complete = bool(latest and latest_spec and latest.payload_json is not None and not latest.pairing_issue
            and latest.actor == "tool" and latest_spec.identity.full_alias_snapshot
            and latest.event_id not in self.records.malformed_record_event_ids
            and not any(position == latest.index for position, _ in self.records.source_issues)
            and conditions_hold(latest_spec.complete_conditions, {"result": latest.payload}))
        # A snapshot only closes its own declared resource/identity universe.
        snapshot_complete = snapshot_complete and latest_spec.identity.namespace == query.namespace and latest_spec.identity.id_field == query.id_field
        if query.entity_mode == "id":
            candidate = EntityRef(query.id_field, query.entity_value, query.namespace)
            entities = (candidate,) if any(record.index <= limit for record in self.records_by_entity.get(candidate, ())) else ()
        else:
            # Latest complete or partial source snapshot, never a confidence pick.
            entities = tuple(sorted({observation.entity for observation in self.records.observations
                if latest and observation.event_id == latest.event_id and query.entity_value in observation.aliases
                and observation.entity.namespace == query.namespace and observation.entity.key == query.id_field},
                key=lambda entity: entity.value))
        complete = bool(entities) and snapshot_complete and self.ledger.history_complete
        rows, searched = [], set()
        expected, _ = decode_json(query.expected_json)
        for entity in entities:
            support, refute, unknown, occurrences, record_count = [], [], [], (), 0
            value = Truth.UNKNOWN
            if query.kind == "FIELD_AT_LAST_READ":
                if latest:
                    searched.add(latest.event_id)
                    proof = prove_scoped_field(ScopedFieldQuery(entity, latest.index, query.field_path, query.expected_json), self.records)
                    record_count = proof.searched_record_count
                    value = proof.value if snapshot_complete else Truth.UNKNOWN
                    if proof.supporting_paths:
                        support.append(latest.event_id)
                    if proof.refuting_paths:
                        refute.append(latest.event_id)
                    if value is Truth.UNKNOWN:
                        unknown.append(latest.event_id)
            elif query.kind == "ALIAS_HISTORY":
                aliases = tuple(item for item in self.records.observations if item.entity == entity and item.index <= limit)
                searched.update(item.event_id for item in aliases)
                support = list(dict.fromkeys(item.event_id for item in aliases if expected in item.aliases))
                relevant_issues = any(event.tool not in self.by_tool or event.payload_json is None or event.pairing_issue
                    or event.event_id in self.records.malformed_record_event_ids
                    or any(position == event.index for position, _ in self.records.source_issues)
                    for event in snapshots if event.tool not in self.by_tool or self.by_tool[event.tool].identity.namespace == query.namespace)
                record_count = len(aliases)
                value = Truth.TRUE if support else Truth.FALSE if self.ledger.history_complete and not relevant_issues else Truth.UNKNOWN
            else:
                mapping_complete = all(any(item.identity == identity and item.namespace == query.namespace and item.id_field == query.id_field
                    and item.argument_entity_path == query.argument_entity_path and item.effect_predicate == query.effect_predicate
                    and item.effect_value_json == query.method_effect_value_json
                    for item in self.methods) for identity in query.method_identities)
                names = {identity.name for identity in query.method_identities}
                candidate_ids = set()
                for name in names:
                    candidate_ids.update(self.events.search(tool=name, event_type="call", time_range=(0, limit)).event_ids)
                calls = []
                for eid in sorted(candidate_ids, key=self.events.positions.__getitem__):
                    event = self.events.events_by_id[eid]
                    if event.actor not in {query.actor, "unknown"} or (query.kind == "CAUSE_OF_METHOD" and event.event_id != query.call_event_id):
                        continue
                    entity_value, present = read_path(event.payload, query.argument_entity_path)
                    if present and (type(entity_value) is not str or entity_value != entity.value):
                        continue
                    calls.append(event)
                occurrences = tuple(self._occurrence(call, query, entity, limit) for call in calls)
                searched.update(call.event_id for call in calls)
                searched.update(eid for occurrence in occurrences for eid in occurrence.result_event_ids)
                support = [item.call_event_id for item in occurrences if item.value is Truth.TRUE]
                refute = [item.call_event_id for item in occurrences if item.value is Truth.FALSE]
                unknown = [item.call_event_id for item in occurrences if item.value in {Truth.UNKNOWN, Truth.BOTH}]
                uncertain = not self.ledger.history_complete or bool(unknown) or not mapping_complete
                if query.kind == "CAUSE_OF_METHOD":
                    value = occurrences[0].value if len(occurrences) == 1 else Truth.UNKNOWN
                elif any(item.value is Truth.BOTH for item in occurrences):
                    value = Truth.BOTH
                elif query.kind == "METHOD_HISTORY":
                    value = Truth.TRUE if support else Truth.UNKNOWN if uncertain else Truth.FALSE
                else:
                    value = Truth.UNKNOWN if uncertain else Truth.TRUE if len(support) == expected else Truth.FALSE
                if query.kind != "METHOD_COMPLETION_COUNT" and expected is False:
                    value = invert(value)
                if not mapping_complete:
                    value = Truth.UNKNOWN
            rows.append(TemporalBinding(entity, value, tuple(support), tuple(refute), tuple(unknown), occurrences, record_count))
        value = consensus(row.value for row in rows)
        # Incomplete history does not erase an existing ID-specific positive
        # source witness. Name binding cannot discard unseen competing identities.
        if query.entity_mode == "name" and not snapshot_complete:
            value = Truth.UNKNOWN
        reasons = []
        if not entities:
            reasons.append(Reason.ENTITY_UNBOUND)
        if len(entities) > 1:
            reasons.append(Reason.ENTITY_AMBIGUOUS)
        if value is Truth.UNKNOWN:
            reasons.append(Reason.CAUSALITY_UNPROVED if query.kind == "CAUSE_OF_METHOD" else Reason.EVIDENCE_INCOMPLETE)
        return TemporalEvidence(query, value, tuple(rows), complete, self.ledger.history_complete,
            latest.event_id if latest else None, tuple(sorted(searched, key=self.events.positions.__getitem__)), tuple(reasons))

    def _occurrence(self, call, query, entity, limit):
        results = tuple(event for event in self.events.events_by_call.get(call.call_id, ()) if event.kind == "result" and event.index <= limit)
        contract = self.registry.lookup(call.tool) if call.tool else None
        actual, present = read_path(call.payload, query.argument_entity_path)
        if call.tool not in query.method_identities or call.actor != query.actor or not present or type(actual) is not str or actual != entity.value:
            return MethodOccurrence(call.event_id, tuple(item.event_id for item in results), Truth.UNKNOWN, (),
                contract.sha256 if contract else None, (Reason.TOOL_VERSION_MISMATCH if contract is None else Reason.ENTITY_UNBOUND,))
        values, effects = [], []
        for result in results:
            semantics = evaluate_t1(self.registry, call, result)
            matching = tuple(effect for effect in semantics.effects if effect.entity.key == ".".join(query.argument_entity_path)
                and effect.entity.value == entity.value and effect.predicate == query.effect_predicate and effect.causal_action_confirmed
                and effect.status is EffectStatus.TRUSTED_EFFECT and effect.value_json == query.method_effect_value_json)
            positive, negative = bool(matching), semantics.no_effect_proved
            values.append(Truth.BOTH if positive and negative else Truth.TRUE if positive else Truth.FALSE if negative else Truth.UNKNOWN)
            effects.extend(effect.effect_id for effect in matching)
        distinct = set(values)
        value = Truth.BOTH if Truth.BOTH in distinct or {Truth.TRUE, Truth.FALSE} <= distinct else consensus(values)
        return MethodOccurrence(call.event_id, tuple(item.event_id for item in results), value, tuple(effects),
            contract.sha256 if contract else None, (Reason.TOOL_EFFECT_UNKNOWN,) if value is Truth.UNKNOWN else ())


def temporal_source_hash(envelope, declarations, registry, query, methods=()):
    return digest({"envelope": asdict(envelope), "snapshots": [asdict(item) for item in declarations],
        "contracts": [asdict(item) for item in registry.contracts], "methods": [asdict(item) for item in methods], "query": asdict(query)})

"""Independent source replay for typed temporal receipts, not Core certificates.

Does not invoke candidate query/index/binder/solver or any semantic backend.
Source framing and T1 evaluation are shared deterministic primitives; binding,
enumeration, counts and temporal aggregation are rebuilt by full source replay.
"""

from dataclasses import asdict, dataclass

from guardian_truth.parsing import decode_json
from .identity_aliases_v2 import records_at
from .integrity import canonical, digest
from .schema_diagnostics import json_equal
from .source_envelope_v4 import normalize_envelope
from .temporal_queries_v4 import MethodOccurrence, TemporalBinding, TemporalEvidence
from .tools import conditions_hold, evaluate_t1, read_path
from .types import EffectStatus, EntityRef, Reason, Truth

SCOPE = "SOURCE_TYPED_TEMPORAL_PRIMITIVE_NOT_CORE_VERDICT_OR_UNRESTRICTED_NL_CLOSURE"
ASSUMPTIONS = (
    "application authenticates source frames and supplied versioned contracts; hashes do not establish authorship",
    "typed query and method/resource mappings are explicit application premises, not LLM entailment proofs",
    "snapshot/history completeness is confined to the declared source/resource scope",
    "not a whole-Core safety proof, unrestricted NL closure or exclusive final-state causation",
)


@dataclass(frozen=True)
class TemporalCertificate:
    version: str
    source_sha256: str
    evidence_sha256: str
    scope: str
    assumptions: tuple[str, ...]


def _unique(values):
    values = set(values)
    return next(iter(values)) if len(values) == 1 else Truth.UNKNOWN


def _negate(value):
    if value is Truth.TRUE:
        return Truth.FALSE
    if value is Truth.FALSE:
        return Truth.TRUE
    return value


def _replay(envelope, declarations, registry, methods, query):
    ledger = normalize_envelope(envelope).ledger
    limit = len(ledger.events) - 1 if query.before_index is None else query.before_index
    if limit < 0 or limit >= len(ledger.events):
        return TemporalEvidence(query, Truth.UNKNOWN, (), False, False, None, (), (Reason.TIME_UNBOUND,))
    specs = {item.identity.tool: item for item in declarations}
    names = {tool.name for tool in specs}
    snapshots = [event for event in ledger.events if event.kind == "result" and event.tool and event.tool.name in names and event.index <= limit]
    latest = snapshots[-1] if snapshots else None
    # Every row carries its original event; no entity information is copied from
    # neighbouring records or flattened observations.
    records, clean = [], {}
    for event in snapshots:
        if event.tool not in specs:
            clean[event.event_id] = False
            continue
        declaration = specs[event.tool].identity
        rows = records_at(event.payload, declaration.record_path) if event.payload_json is not None and not event.pairing_issue else []
        clean[event.event_id] = bool(rows) and event.actor == "tool"
        for row, _ in rows:
            expected_type = str if declaration.id_type == "string" else int
            if not isinstance(row, dict) or type(row.get(declaration.id_field)) is not expected_type or not str(row[declaration.id_field]):
                clean[event.event_id] = False
                continue
            entity = EntityRef(declaration.id_field, str(row[declaration.id_field]), declaration.namespace)
            aliases = []
            for field in declaration.alias_fields:
                if field not in row:
                    clean[event.event_id] = False
                    continue
                raw = row[field] if isinstance(row[field], list) else [row[field]]
                if any(type(item) is not str or not item for item in raw):
                    clean[event.event_id] = False
                aliases.extend(item for item in raw if type(item) is str and item)
            records.append((entity, event, row, tuple(aliases)))
    spec = specs.get(latest.tool) if latest else None
    snapshot_complete = bool(latest and spec and clean.get(latest.event_id) and spec.identity.full_alias_snapshot
        and spec.identity.namespace == query.namespace and spec.identity.id_field == query.id_field
        and conditions_hold(spec.complete_conditions, {"result": latest.payload}))
    if query.entity_mode == "id":
        wanted = EntityRef(query.id_field, query.entity_value, query.namespace)
        entities = [wanted] if any(entity == wanted for entity, _, _, _ in records) else []
    else:
        entities = sorted({entity for entity, event, _, aliases in records if latest and event.event_id == latest.event_id
            and query.entity_value in aliases and entity.namespace == query.namespace and entity.key == query.id_field}, key=lambda item: item.value)
    expected, _ = decode_json(query.expected_json)
    bindings, searched = [], set()
    for entity in entities:
        support, refute, unknown, occurrences, count = [], [], [], [], 0
        value = Truth.UNKNOWN
        if query.kind == "FIELD_AT_LAST_READ":
            if latest:
                searched.add(latest.event_id)
                own = [row for selected, event, row, _ in records if selected == entity and event.event_id == latest.event_id]
                count = len(own)
                answers = []
                for row in own:
                    actual, present = read_path(row, query.field_path)
                    answers.append(None if not present else json_equal(actual, expected))
                if True in answers:
                    support.append(latest.event_id)
                if False in answers:
                    refute.append(latest.event_id)
                value = Truth.BOTH if True in answers and False in answers else Truth.UNKNOWN if None in answers or not snapshot_complete else Truth.TRUE if True in answers else Truth.FALSE if False in answers else Truth.UNKNOWN
                # The candidate refuses non-authoritative snapshot scope even
                # when recorded fields conflict. Replay enforces that boundary.
                if not snapshot_complete:
                    value = Truth.UNKNOWN
                if value is Truth.UNKNOWN:
                    unknown.append(latest.event_id)
        elif query.kind == "ALIAS_HISTORY":
            own = [(event, aliases) for selected, event, _, aliases in records if selected == entity]
            count = len(own)
            searched.update(event.event_id for event, _ in own)
            support = list(dict.fromkeys(event.event_id for event, aliases in own if expected in aliases))
            incomplete = any(not clean.get(event.event_id) for event in snapshots if event.tool not in specs or specs[event.tool].identity.namespace == query.namespace)
            value = Truth.TRUE if support else Truth.FALSE if ledger.history_complete and not incomplete else Truth.UNKNOWN
        else:
            mapping_complete = True
            for identity in query.method_identities:
                matching = [item for item in methods if item.identity == identity and item.namespace == query.namespace and item.id_field == query.id_field
                    and item.argument_entity_path == query.argument_entity_path and item.effect_predicate == query.effect_predicate
                    and item.effect_value_json == query.method_effect_value_json]
                if len(matching) != 1:
                    mapping_complete = False
            names = {item.name for item in query.method_identities}
            for call in ledger.events:
                if call.index > limit or call.kind != "call" or not call.tool or call.tool.name not in names or call.actor not in {query.actor, "unknown"}:
                    continue
                if query.kind == "CAUSE_OF_METHOD" and call.event_id != query.call_event_id:
                    continue
                actual, present = read_path(call.payload, query.argument_entity_path)
                if present and (type(actual) is not str or actual != entity.value):
                    continue
                results = [event for event in ledger.events if event.kind == "result" and event.index <= limit and call.call_id is not None and event.call_id == call.call_id]
                searched.add(call.event_id)
                searched.update(event.event_id for event in results)
                contract = registry.lookup(call.tool)
                effects, answers = [], []
                compatible = call.tool in query.method_identities and call.actor == query.actor and present and type(actual) is str and actual == entity.value
                if not compatible:
                    occurrence = MethodOccurrence(call.event_id, tuple(event.event_id for event in results), Truth.UNKNOWN, (),
                        contract.sha256 if contract else None, (Reason.TOOL_VERSION_MISMATCH if contract is None else Reason.ENTITY_UNBOUND,))
                else:
                    for result in results:
                        semantics = evaluate_t1(registry, call, result)
                        positive = []
                        for effect in semantics.effects:
                            if effect.entity.key == ".".join(query.argument_entity_path) and effect.entity.value == entity.value and effect.predicate == query.effect_predicate and effect.causal_action_confirmed and effect.status is EffectStatus.TRUSTED_EFFECT and effect.value_json == query.method_effect_value_json:
                                positive.append(effect.effect_id)
                        effects.extend(positive)
                        answers.append(Truth.BOTH if positive and semantics.no_effect_proved else Truth.TRUE if positive else Truth.FALSE if semantics.no_effect_proved else Truth.UNKNOWN)
                    occurrence_value = Truth.BOTH if Truth.BOTH in answers or Truth.TRUE in answers and Truth.FALSE in answers else _unique(answers)
                    occurrence = MethodOccurrence(call.event_id, tuple(event.event_id for event in results), occurrence_value, tuple(effects),
                        contract.sha256 if contract else None, (Reason.TOOL_EFFECT_UNKNOWN,) if occurrence_value is Truth.UNKNOWN else ())
                occurrences.append(occurrence)
            support = [item.call_event_id for item in occurrences if item.value is Truth.TRUE]
            refute = [item.call_event_id for item in occurrences if item.value is Truth.FALSE]
            unknown = [item.call_event_id for item in occurrences if item.value in {Truth.UNKNOWN, Truth.BOTH}]
            if query.kind == "CAUSE_OF_METHOD":
                value = occurrences[0].value if len(occurrences) == 1 else Truth.UNKNOWN
            elif any(item.value is Truth.BOTH for item in occurrences):
                value = Truth.BOTH
            elif query.kind == "METHOD_HISTORY":
                value = Truth.TRUE if support else Truth.UNKNOWN if unknown or not ledger.history_complete else Truth.FALSE
            else:
                value = Truth.UNKNOWN if unknown or not ledger.history_complete else Truth.TRUE if len(support) == expected else Truth.FALSE
            if query.kind != "METHOD_COMPLETION_COUNT" and expected is False:
                value = _negate(value)
            if not mapping_complete:
                value = Truth.UNKNOWN
        bindings.append(TemporalBinding(entity, value, tuple(support), tuple(refute), tuple(unknown), tuple(occurrences), count))
    value = _unique(row.value for row in bindings)
    if query.entity_mode == "name" and not snapshot_complete:
        value = Truth.UNKNOWN
    reasons = []
    if not entities:
        reasons.append(Reason.ENTITY_UNBOUND)
    if len(entities) > 1:
        reasons.append(Reason.ENTITY_AMBIGUOUS)
    if value is Truth.UNKNOWN:
        reasons.append(Reason.CAUSALITY_UNPROVED if query.kind == "CAUSE_OF_METHOD" else Reason.EVIDENCE_INCOMPLETE)
    return TemporalEvidence(query, value, tuple(bindings), bool(entities) and snapshot_complete and ledger.history_complete,
        ledger.history_complete, latest.event_id if latest else None,
        tuple(event.event_id for event in ledger.events if event.event_id in searched), tuple(reasons))


def _source_hash(envelope, declarations, registry, query, methods):
    return digest({"envelope": asdict(envelope), "snapshots": [asdict(item) for item in declarations],
        "contracts": [asdict(item) for item in registry.contracts], "methods": [asdict(item) for item in methods], "query": asdict(query)})


def check_temporal_evidence(envelope, declarations, registry, methods, evidence):
    if not isinstance(evidence, TemporalEvidence) or evidence.scope != SCOPE:
        return ("TEMPORAL_SCOPE_OR_FORMAT_CHANGED",)
    replayed = _replay(envelope, declarations, registry, methods, evidence.query)
    return () if evidence == replayed else ("SOURCE_REPLAY_MISMATCH",)


def make_temporal_certificate(envelope, declarations, registry, methods, evidence):
    if check_temporal_evidence(envelope, declarations, registry, methods, evidence):
        raise ValueError("temporal evidence failed independent source replay")
    return TemporalCertificate("guardian-typed-temporal-receipt-v4", _source_hash(envelope, declarations, registry, evidence.query, methods),
        digest(asdict(evidence)), SCOPE, ASSUMPTIONS)


def validate_temporal_certificate(certificate, envelope, declarations, registry, methods, evidence):
    if not isinstance(certificate, TemporalCertificate):
        return False
    expected = TemporalCertificate("guardian-typed-temporal-receipt-v4", _source_hash(envelope, declarations, registry, evidence.query, methods),
        digest(asdict(evidence)), SCOPE, ASSUMPTIONS)
    return certificate == expected and not check_temporal_evidence(envelope, declarations, registry, methods, evidence)

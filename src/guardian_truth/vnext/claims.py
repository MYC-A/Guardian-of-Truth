"""Deterministic response inventories followed by ten narrow semantic passes."""

from __future__ import annotations

from dataclasses import dataclass

from guardian_truth.cycle2.claims import response_spans
from .semantic import SemanticBackend, schema_valid
from .types import ClaimKind, ClaimRelation, Disposition, Reason, Span, TypedClaim


PASSES = (
    ("claim_disposition", "disposition", {"type": "string", "enum": [item.value for item in Disposition]}),
    ("claim_kind", "kind", {"type": "string", "enum": [item.value for item in ClaimKind] + ["UNKNOWN", "NON_VERIFIABLE"]}),
    ("claim_actor", "actor", {"type": "string"}),
    ("claim_predicate", "predicate", {"type": "string"}),
    ("claim_object_entities", None, None),
    ("claim_modality_polarity", None, None),
    ("claim_time", "time_anchor", {"type": "string"}),
    ("claim_source", "source_refs", {"type": "array", "items": {"type": "string"}, "uniqueItems": True}),
    ("claim_relations", None, None),
    ("claim_explicit_causality", "explicit_causality", {"anyOf": [{"type": "boolean"}, {"type": "null"}]}),
)
RELATIONS = ["refers_to", "causes", "supports", "contradicts", "same_entity", "same_event"]
TASK_INSTRUCTIONS = {
    "claim_disposition": "Classify each span as a verifiable semantic proposition, NON_VERIFIABLE politeness/opinion, or UNKNOWN_SEMANTICS. Verifiable does not mean true. Never drop a span.",
    "claim_kind": "Distinguish STATE (a condition), ACTION_COMPLETED (asserted completion), INTENT (future/planned action), CAUSAL_ATTRIBUTION (explicit claim an event caused a state), ACTION_FAILED, ATTRIBUTION (what another source said), REFUSAL, ABSENCE, PERMISSION and FACT. An action claim is not evidence that it happened.",
    "claim_actor": "Identify the actor of the claimed action/state or attributed assertion, not merely the speaker. 'I' is assistant; 'you' is user. Use a named actor exactly as stated, entity for entity state, and UNKNOWN when unresolved.",
    "claim_predicate": "Identify a short predicate/action/state; preserve whether the span claims archive as an action or archived as a state. UNKNOWN is allowed. Do not invent a tool identity from a verb.",
    "claim_object_entities": "Return the object and all explicitly mentioned entity strings. Do not invent IDs, merge same-name entities, or resolve pronouns to guessed identifiers. Empty entity_refs is allowed for genuinely unspecified entities; use object UNKNOWN for unresolved objects.",
    "claim_modality_polarity": "Separate asserted, reported, intended, possible, inability and permission. Negation changes polarity, not certainty. 'Perhaps' is POSSIBLE, 'will' is INTENT, 'tool reports' is REPORTED. Unknown is not negative.",
    "claim_time": "Return NOW, PAST, FUTURE, YESTERDAY, ALL_HISTORY, UNSPECIFIED, an explicit quoted temporal anchor, or UNKNOWN. 'Never' is ALL_HISTORY; current existence does not contradict an earlier deletion.",
    "claim_source": "Return the attributed source(s), not automatically the speaker. ASSISTANT is an unattributed assistant claim; USER for 'you said'; TOOL for 'tool reports'; SYSTEM for an explicit system citation. Use explicitly named sources if present; UNKNOWN when attribution is unresolved.",
    "claim_relations": "Return only claim-to-claim relations explicitly supported by the response. Pronouns may refer_to another claim; claimed causation is causes, not proof. Cite deterministic grounding_span_ids. Empty relations is allowed. No self-relations or guessed causal links.",
    "claim_explicit_causality": "For every span say whether it explicitly attributes a state/outcome to a causal event (true), does not do so (false), or is ambiguous (null). 'Is archived' alone is false; 'my call made it archived' is true. This does not establish real causality.",
}


@dataclass(frozen=True)
class ClaimGraph:
    response_sha256: str
    claims: tuple[TypedClaim, ...]
    relations: tuple[ClaimRelation, ...]
    failures: tuple[tuple[str, Reason], ...]
    explicit_causality: tuple[tuple[str, bool | None], ...]


def task_schema(task: str, spans: list[dict]) -> dict:
    ids = [span["span_id"] for span in spans]
    if task == "claim_relations":
        relation = {"type": "object", "additionalProperties": False,
            "required": ["subject", "relation", "object", "grounding_span_ids"],
            "properties": {"subject": {"type": "string", "enum": ids},
                "object": {"type": "string", "enum": ids},
                "relation": {"type": "string", "enum": RELATIONS},
                "grounding_span_ids": {"type": "array", "items": {"type": "string", "enum": ids},
                                       "minItems": 1, "uniqueItems": True}}}
        return {"type": "object", "additionalProperties": False, "required": ["relations"],
                "properties": {"relations": {"type": "array", "items": relation, "uniqueItems": True}}}
    _, field, spec = next(item for item in PASSES if item[0] == task)
    properties = {"span_id": {"type": "string", "enum": ids}}
    if task == "claim_object_entities":
        properties.update({"object": {"type": "string"}, "entity_refs": {"type": "array", "items": {"type": "string"}, "uniqueItems": True}})
    elif task == "claim_modality_polarity":
        properties.update({"modality": {"type": "string", "enum": ["ASSERTED", "INTENT", "POSSIBLE", "REPORTED", "INABILITY", "PERMISSION", "UNKNOWN", "UNSPECIFIED"]},
                           "polarity": {"type": "string", "enum": ["POSITIVE", "NEGATIVE", "UNKNOWN"]}})
    else:
        properties[field] = spec
    item = {"type": "object", "additionalProperties": False,
            "required": list(properties), "properties": properties}
    return {"type": "object", "additionalProperties": False, "required": ["spans"],
            "properties": {"spans": {"type": "array", "items": item, "minItems": len(ids), "maxItems": len(ids)}}}


def build_claim_graph(response: str, backend: SemanticBackend) -> ClaimGraph:
    from .integrity import digest
    inventory = response_spans(response)
    if not inventory:
        return ClaimGraph(digest(response), (), (), (), ())
    ids = {span["span_id"] for span in inventory}
    semantics = {sid: {} for sid in ids}
    failures, relations = [], []
    for task, _, _ in PASSES:
        schema = task_schema(task, inventory)
        # Model receives inventory IDs/text, NEVER generates source offsets.
        payload = {"span_inventory": [{"span_id": span["span_id"], "text": span["text"]} for span in inventory],
                   "unknown_convention": "UNKNOWN for uncertain strings; null for uncertain explicit causality",
                   "entity_convention": "entity_refs must be exact strings explicitly present in response; do not invent IDs",
                   "task_instructions": TASK_INSTRUCTIONS[task],
                   "task_scope": "Interpret only this field/pass. Keep actor, intent, observed state and causality distinct."}
        proposal = backend.propose(task, payload, schema)
        if proposal.transport_status != "SUCCESS":
            failures.append((task, Reason.TRANSPORT_ERROR))
            continue
        value = proposal.value
        if proposal.schema_status != "VALID" or not schema_valid(value, schema):
            failures.append((task, Reason.SCHEMA_ERROR))
            continue
        if task == "claim_relations":
            for item in value["relations"]:
                if item["subject"] == item["object"]:
                    failures.append((task, Reason.SCHEMA_ERROR))
                    continue
                relations.append(item)
        else:
            items = value["spans"]
            returned = [item["span_id"] for item in items]
            if len(set(returned)) != len(returned) or set(returned) != ids:
                failures.append((task, Reason.SCHEMA_ERROR))
                continue
            for item in items:
                semantics[item["span_id"]].update({key: val for key, val in item.items() if key != "span_id"})
    claims, causality = [], []
    by_id = {span["span_id"]: span for span in inventory}
    for span in inventory:
        sid = span["span_id"]
        fields = semantics[sid]
        disposition = Disposition(fields.get("disposition", "UNKNOWN_SEMANTICS"))
        kind = fields.get("kind")
        kind = ClaimKind(kind) if kind in {item.value for item in ClaimKind} else None
        unknown = [key for key in ("kind", "actor", "predicate", "object", "polarity", "modality", "time_anchor", "source_refs")
                   if fields.get(key) in (None, "UNKNOWN", [], "")]
        if kind is None and "kind" not in unknown:
            unknown.append("kind")
        if "UNKNOWN" in fields.get("source_refs", ()):
            if "source_refs" not in unknown:
                unknown.append("source_refs")
        entities = tuple(fields.get("entity_refs", ()))
        if any(entity not in response for entity in entities):
            unknown.append("entity_refs")
            entities = ()
        if kind is ClaimKind.CAUSAL_ATTRIBUTION and fields.get("explicit_causality") is not True:
            unknown.append("explicit_causality")
        if disposition is Disposition.VERIFIABLE_TYPED and unknown:
            disposition = Disposition.UNKNOWN_SEMANTICS
        claims.append(TypedClaim(sid, Span("response", span["start"], span["end"]), disposition, kind,
                                 fields.get("actor"), fields.get("predicate"), fields.get("object"), entities,
                                 fields.get("polarity"), fields.get("modality"), fields.get("time_anchor"),
                                 tuple(fields.get("source_refs", ())), tuple(unknown)))
        causality.append((sid, fields.get("explicit_causality")))
    typed_relations = tuple(ClaimRelation(item["subject"], item["relation"], item["object"],
            tuple(Span("response", by_id[sid]["start"], by_id[sid]["end"]) for sid in item["grounding_span_ids"]))
            for item in relations)
    return ClaimGraph(digest(response), tuple(claims), typed_relations, tuple(failures), tuple(causality))

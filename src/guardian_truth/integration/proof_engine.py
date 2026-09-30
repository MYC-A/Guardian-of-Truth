"""Proof queries over reviewed policy programs and verified WorldFacts.

The program is explicitly reviewed/oracle input. This module proves scoped,
time-bounded implications of that program; it does not acquire policy rules
from prose. Missing evidence stays UNKNOWN, including a missing prerequisite.
"""
from __future__ import annotations

from dataclasses import dataclass
import json

from guardian_truth.integration.contracts import acquire_documented
from guardian_truth.integration.claim_binding import _literal_occurs
from guardian_truth.step2.ledger import FactLedger
from guardian_truth.step2.result_types import scalar_to_json
from guardian_truth.step2.trusted import producer_scope
from guardian_truth.step2.types import EffectStrength, FactEvent, LedgerKind, Truth
from guardian_truth.step2.verifier import CallEvent, TrajectoryCase, VerifiedFact


@dataclass(frozen=True)
class ReviewedProgram:
    policy: str
    governed_tool: str
    governed_description: str
    governed_producer: str
    entity_argument: str
    gate: dict
    when: dict | None = None
    evidence_source: str = ""
    complete_for_governed_action: bool = False

    def __post_init__(self):
        if self.evidence_source not in {"HUMAN_REVIEWED", "DOC_EXPLICIT", "ENV_TESTED"}:
            raise ValueError("model-generated policy cannot mark itself reviewed")
        if (not self.policy or not self.governed_tool or not self.governed_producer
                or not isinstance(self.gate, dict)):
            raise ValueError("source policy, governed tool, and gate required")


def _answer(status: str, reason: str, **evidence) -> dict:
    return {"status": status, "reason": reason, **evidence}


def _atom(query: dict, program: ReviewedProgram, target: CallEvent,
          case: TrajectoryCase, facts: tuple[VerifiedFact, ...]) -> dict:
    needed = ("predicate", "entity_type", "value", "allowed_strengths", "scope_joins")
    if any(key not in query for key in needed):
        return _answer("UNKNOWN", "atom_incomplete")
    if not isinstance(target.payload, dict) or program.entity_argument not in target.payload:
        return _answer("UNKNOWN", "target_entity_unbound")
    entity = scalar_to_json(target.payload[program.entity_argument])
    required = scalar_to_json(query["value"])
    if entity is None or required is None:
        return _answer("UNKNOWN", "atom_value_not_scalar")
    joins = query["scope_joins"]
    if not isinstance(joins, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                               for k, v in joins.items()):
        return _answer("UNKNOWN", "scope_joins_invalid")
    allowed = query["allowed_strengths"]
    if not isinstance(allowed, list) or not allowed or any(x not in EffectStrength._value2member_map_
                                                              for x in allowed):
        return _answer("UNKNOWN", "strength_contract_invalid")
    scoped = FactLedger()
    unresolved_time: list[int] = []
    for verified in facts:
        fact = verified.fact
        if (fact.predicate != query["predicate"] or fact.entity_type != query["entity_type"]
                or fact.entity_id != entity or fact.observed_at >= target.index):
            continue
        sources = [call for call in case.calls if call.call_id == fact.provenance.call_id]
        if len(sources) != 1 or not isinstance(sources[0].payload, dict):
            unresolved_time.append(fact.observed_at)
            continue
        source = sources[0].payload
        if any(a not in target.payload or b not in source for a, b in joins.items()):
            unresolved_time.append(fact.observed_at)
            continue
        if any(scalar_to_json(target.payload[a]) != scalar_to_json(source[b])
               for a, b in joins.items()):
            continue
        scoped.append(FactEvent(fact.observed_at,
                                LedgerKind.OBSERVE if fact.strength is EffectStrength.OBSERVED
                                else LedgerKind.EFFECT, fact))
    view = scoped.latest(query["entity_type"], entity, query["predicate"],
                         as_of=target.index - 1)
    if view.truth is Truth.UNKNOWN or view.provenance is None:
        return _answer("UNKNOWN", "no_prior_scoped_fact", cutoff=target.index - 1)
    if any(index >= view.observed_at for index in unresolved_time):
        return _answer("UNKNOWN", "newer_scope_unresolved", fact=view.as_dict())
    if view.strength is None or view.strength.value not in allowed:
        return _answer("UNKNOWN", "condition_strength_unproven", fact=view.as_dict())
    return _answer("SATISFIED" if view.value == required else "VIOLATION",
                   "latest_prior_scoped_fact", required_value=required,
                   fact=view.as_dict(), cutoff=target.index - 1)


def _gate(node: dict, program: ReviewedProgram, target: CallEvent,
          case: TrajectoryCase, facts: tuple[VerifiedFact, ...]) -> dict:
    if not isinstance(node, dict) or len(node) != 1:
        return _answer("UNKNOWN", "gate_invalid")
    operator, body = next(iter(node.items()))
    if operator == "source" and isinstance(body, dict) and set(body) == {"start", "end", "gate"}:
        start, end = body["start"], body["end"]
        if (type(start) is not int or type(end) is not int or start < 0
                or end <= start or end > len(program.policy)):
            return _answer("UNKNOWN", "policy_span_invalid")
        quote = program.policy[start:end]
        child = _gate(body["gate"], program, target, case, facts)
        return {**child, "source": {"start": start, "end": end,
                                     "quote": quote, "review": program.evidence_source}}
    if operator == "atom" and isinstance(body, dict):
        return _atom(body, program, target, case, facts)
    if operator in {"all", "any"} and isinstance(body, list) and body:
        children = [_gate(child, program, target, case, facts) for child in body]
        statuses = {child["status"] for child in children}
        if operator == "all":
            status = ("VIOLATION" if "VIOLATION" in statuses else
                      "SATISFIED" if statuses == {"SATISFIED"} else "UNKNOWN")
        else:
            status = ("SATISFIED" if "SATISFIED" in statuses else
                      "VIOLATION" if statuses == {"VIOLATION"} else "UNKNOWN")
        return _answer(status, operator, children=children)
    if operator == "unless" and isinstance(body, dict) and set(body) == {"base", "exception"}:
        base = _gate(body["base"], program, target, case, facts)
        exception = _gate(body["exception"], program, target, case, facts)
        # Exception must itself be proven; missing evidence cannot waive base.
        if base["status"] == "SATISFIED" or exception["status"] == "SATISFIED":
            status = "SATISFIED"
        elif base["status"] == "VIOLATION" and exception["status"] == "VIOLATION":
            status = "VIOLATION"
        else:
            status = "UNKNOWN"
        return _answer(status, "unless", children=[base, exception])
    return _answer("UNKNOWN", "operator_unsupported")


def check_call(program: ReviewedProgram, case: TrajectoryCase, target: CallEvent,
               facts: tuple[VerifiedFact, ...]) -> dict:
    """Prove an attempted governed call's prerequisites as of call time."""
    source = {"quote": program.policy, "start": 0, "end": len(program.policy),
              "review": program.evidence_source}
    if case.category != program.policy:
        return _answer("UNKNOWN", "policy_source_mismatch", source=source)
    matching_tools = [t for t in case.tools if t.get("name") == program.governed_tool]
    if (len(matching_tools) != 1
            or matching_tools[0].get("description") != program.governed_description
            or producer_scope(case, program.governed_tool) != program.governed_producer):
        return _answer("UNKNOWN", "governed_producer_unverified", source=source)
    if target.tool != program.governed_tool:
        return _answer("NOT_APPLICABLE", "different_tool", source=source)
    if ([c for c in case.calls if c.call_id == target.call_id] != [target]
            or target.actor != "assistant"):
        return _answer("UNKNOWN", "target_call_unverified", source=source)
    if program.when is not None:
        guard = program.when
        if not isinstance(guard, dict) or set(guard) != {"field", "op", "value"}:
            return _answer("UNKNOWN", "activation_guard_invalid", source=source)
        if not isinstance(target.payload, dict) or guard["field"] not in target.payload:
            return _answer("UNKNOWN", "activation_field_missing", source=source)
        actual, expected = target.payload[guard["field"]], guard["value"]
        if (isinstance(actual, bool) or not isinstance(actual, (int, float))
                or isinstance(expected, bool) or not isinstance(expected, (int, float))):
            return _answer("UNKNOWN", "activation_value_not_numeric", source=source)
        if guard["op"] != "GT":
            return _answer("UNKNOWN", "activation_op_unsupported", source=source)
        if not actual > expected:
            return _answer("NOT_APPLICABLE", "activation_false", source=source)
    proof = _gate(program.gate, program, target, case, facts)
    return {**proof, "target_call_id": target.call_id,
            "target_index": target.index, "cutoff": target.index - 1,
            "source": source}


def load_reviewed_programs(path) -> tuple[ReviewedProgram, ...]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("track") != "human_reviewed_oracle":
        raise ValueError("untrusted reviewed-program file")
    return tuple(ReviewedProgram(**entry) for entry in value["programs"])


@dataclass(frozen=True)
class ClaimQuery:
    response: str
    response_index: int
    quote: str
    start: int
    end: int
    mode: str
    predicate: str
    entity_type: str
    entity_value: str
    expected_value: object
    evidence_source: str
    actor: str = "UNKNOWN"
    scope_arguments: tuple[tuple[str, str], ...] = ()
    scope_span: tuple[int, int] | None = None


def _claim_scoped_facts(query: ClaimQuery, case: TrajectoryCase,
                        facts: tuple[VerifiedFact, ...]) -> tuple[VerifiedFact, ...]:
    """Require every documented producer argument to be claim-bound.

    A fact about an order at amount 100 must not license a claim about amount
    250. Absent claim scope yields no supporting fact, never a negative fact.
    """
    claim_scope = dict(query.scope_arguments)
    if len(claim_scope) != len(query.scope_arguments):
        return ()
    acquired = acquire_documented(case)
    scoped = []
    for verified in facts:
        fact = verified.fact
        if (fact.predicate != query.predicate or fact.entity_type != query.entity_type
                or fact.entity_id != scalar_to_json(query.entity_value)
                or fact.observed_at >= query.response_index):
            continue
        sources = [c for c in case.calls if c.call_id == fact.provenance.call_id]
        if len(sources) != 1 or not isinstance(sources[0].payload, dict):
            continue
        call = sources[0]
        producer = producer_scope(case, call.tool)
        bindings = [b for b in acquired.bindings
                    if b.producer == producer and b.predicate == fact.predicate
                    and b.entity_type == fact.entity_type
                    and b.result_path == fact.provenance.json_path
                    and b.strength == fact.strength
                    and (not b.allowed_values or fact.value in b.allowed_values)]
        catalog = [t for t in case.tools if t.get("name") == call.tool]
        if len(bindings) != 1 or len(catalog) != 1:
            continue
        entity_field = bindings[0].entity_field
        params = catalog[0].get("parameters", {})
        if not isinstance(params, dict):
            continue
        extra_fields = set(params) - {entity_field}
        if set(claim_scope) != extra_fields:
            continue
        if any(field not in call.payload
               or scalar_to_json(call.payload[field]) != claim_scope[field]
               for field in extra_fields):
            continue
        scoped.append(verified)
    return tuple(scoped)


def check_claim(query: ClaimQuery, case: TrajectoryCase,
                facts: tuple[VerifiedFact, ...]) -> dict:
    """Ask whether a source-exact response claim has a current proof path.

    A missing fact is UNKNOWN, never a contradiction. A latest authoritative
    read can contradict a *current state* claim. It cannot automatically
    disprove that a possibly reversible action happened earlier.
    """
    source = {"quote": query.quote, "start": query.start, "end": query.end,
              "interpretation": query.evidence_source}
    if (query.start < 0 or query.end > len(query.response)
            or query.start >= query.end
            or query.response[query.start:query.end] != query.quote):
        return _answer("UNKNOWN", "claim_source_mismatch", source=source)
    scope_start, scope_end = query.scope_span or (query.start, query.end)
    if (scope_start < 0 or scope_end > len(query.response)
            or scope_start > query.start or scope_end < query.end):
        return _answer("UNKNOWN", "claim_scope_source_mismatch", source=source)
    scope_text = query.response[scope_start:scope_end]
    for field, canonical in query.scope_arguments:
        try:
            raw = json.loads(canonical)
        except (TypeError, ValueError):
            return _answer("UNKNOWN", "claim_scope_value_invalid", source=source)
        if not isinstance(field, str) or scalar_to_json(raw) != canonical or not _literal_occurs(
                scope_text, str(raw).lower() if isinstance(raw, bool) else str(raw)):
            return _answer("UNKNOWN", "claim_scope_not_source_grounded", source=source)
    if query.mode in {"PROPOSED", "CONDITIONAL", "REQUEST", "REFUSAL"}:
        return _answer("NOT_APPLICABLE", "not_a_factual_completion_or_state", source=source)
    if query.mode not in {"CLAIMED_COMPLETED", "STATE_CLAIM"}:
        return _answer("UNKNOWN", "claim_mode_unresolved", source=source)
    entity = scalar_to_json(query.entity_value)
    expected = scalar_to_json(query.expected_value)
    if entity is None or expected is None or not query.predicate or not query.entity_type:
        return _answer("UNKNOWN", "claim_semantics_unbound", source=source)
    scoped_facts = _claim_scoped_facts(query, case, facts)
    if query.mode == "CLAIMED_COMPLETED" and query.actor == "ASSISTANT":
        # A later read can prove the state but not that this agent caused it.
        # The claim "I did X" needs a witnessed effect of an assistant call.
        causal = []
        for verified in scoped_facts:
            fact = verified.fact
            if (fact.observed_at >= query.response_index
                    or fact.predicate != query.predicate
                    or fact.entity_type != query.entity_type
                    or fact.entity_id != entity or fact.value != expected
                    or fact.strength is not EffectStrength.EXECUTED):
                continue
            causal.append(fact)
        if not causal:
            return _answer("UNKNOWN", "assistant_effect_unproven", source=source,
                           cutoff=query.response_index - 1)
        latest_effect = max(causal, key=lambda fact: fact.observed_at)
        return _answer("SUPPORTED", "witnessed_assistant_effect",
                       source=source, cutoff=query.response_index - 1,
                       fact=latest_effect.as_dict(), expected_value=expected)
    if query.mode == "CLAIMED_COMPLETED" and query.actor not in {"UNSPECIFIED", "OTHER"}:
        return _answer("UNKNOWN", "completed_actor_unresolved", source=source)
    ledger = FactLedger()
    for verified in scoped_facts:
        fact = verified.fact
        if fact.observed_at >= query.response_index:
            continue
        ledger.append(FactEvent(fact.observed_at,
                                LedgerKind.OBSERVE if fact.strength is EffectStrength.OBSERVED
                                else LedgerKind.EFFECT, fact))
    view = ledger.latest(query.entity_type, entity, query.predicate,
                         as_of=query.response_index - 1)
    if view.truth is Truth.UNKNOWN or view.provenance is None:
        return _answer("UNKNOWN", "no_semantically_bound_fact", source=source,
                       cutoff=query.response_index - 1)
    proof = {"source": source, "cutoff": query.response_index - 1,
             "fact": view.as_dict(), "expected_value": expected}
    if view.value == expected:
        if view.strength in {EffectStrength.REQUESTED, EffectStrength.INITIATED}:
            return _answer("PENDING", "only_request_or_initiation", **proof)
        if (query.mode == "CLAIMED_COMPLETED"
                and view.strength not in {EffectStrength.EXECUTED, EffectStrength.CONFIRMED,
                                          EffectStrength.OBSERVED}):
            return _answer("UNKNOWN", "completion_strength_unproven", **proof)
        return _answer("SUPPORTED", "exact_current_fact", **proof)
    if view.strength in {EffectStrength.REQUESTED, EffectStrength.INITIATED}:
        return _answer("PENDING", "only_request_or_initiation", **proof)
    if query.mode == "STATE_CLAIM" and view.strength is EffectStrength.OBSERVED:
        return _answer("CONTRADICTED", "latest_read_disagrees_with_current_state", **proof)
    return _answer("UNKNOWN", "different_value_does_not_refute_past_action", **proof)


def decide_reviewed(action_proofs: tuple[dict, ...], claim_proofs: tuple[dict, ...],
                    *, policy_complete: bool, claim_inventory_complete: bool) -> dict:
    """Three-valued verdict for a completely declared reviewed scope.

    Explicit violations and contradictions suffice for ERROR. NO_ERROR needs
    complete policy/claim inventory and every applicable proof discharged.
    """
    if any(p["status"] == "VIOLATION" for p in action_proofs):
        return _answer("ERROR", "proven_policy_violation", actions=list(action_proofs),
                       claims=list(claim_proofs))
    if any(p["status"] == "CONTRADICTED" for p in claim_proofs):
        return _answer("ERROR", "proven_current_state_contradiction",
                       actions=list(action_proofs), claims=list(claim_proofs))
    unresolved = {"UNKNOWN", "PENDING"}
    if (not policy_complete or not claim_inventory_complete
            or any(p["status"] in unresolved for p in action_proofs + claim_proofs)):
        return _answer("UNKNOWN", "proof_or_inventory_incomplete",
                       actions=list(action_proofs), claims=list(claim_proofs))
    return _answer("NO_ERROR", "reviewed_scope_fully_discharged",
                   actions=list(action_proofs), claims=list(claim_proofs))

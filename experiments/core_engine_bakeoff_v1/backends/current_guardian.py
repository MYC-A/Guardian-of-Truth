"""core_engine_bakeoff_v1 — backend: CURRENT GUARDIAN CORE (baseline).

NeutralCoreInput -> incumbent EvidenceLedger + ContractRegistry + obligations
-> the REAL incumbent solver stack:

    ledger (vnext.ledger)  +  T1 contracts (vnext.tools.evaluate_t1)
    -> world integration (e2e.world_integration_v1.build_worlds /
       make_problem / solve_e2e) with PRODUCTION semantics FULL_SEMANTICS
       (B3: conservative_state + inconsistent_status)
    -> vnext.types.consensus -> CoreStatus

No production file is modified.  The adapter is a TRANSLATION layer only:
it materializes the already-classified NeutralFacts through the incumbent's
own evidence machinery (reader contracts for observations, writer contracts
with regenerated effects for completions, uncontracted calls for bare
attempts / failures), then lets the incumbent evaluate.

Honest representability limits surfaced as UNRESOLVED markers (never silent
approximation), mirroring what the incumbent's own lowering does:
  - comparison atoms: no incumbent primitive  -> unresolved marker
  - cardinality atoms: no incumbent primitive -> unresolved marker
  - condition disjunction (any-nodes): compile_h0 conditions are a flat
    conjunction; GRS CHOICE is explicitly 'not expressible in V1' -> marker
  - completed-level rules with a wildcard entity: ACTION_COMPLETED atoms
    have no wildcard form -> marker
State atoms are routed through the incumbent's CONSERVATIVE current-state
evaluator (OBSERVED_STATE @ LATEST, SND-02 staleness) — the production B3
semantics for current-state queries.  (The incumbent's policy-condition
fallback path skips the staleness rule; that dual-path discrepancy is
recorded in the bake-off report as a finding, and the experiment pins the
conservative semantics as the reference.)
"""

from __future__ import annotations

import sys
import time
from dataclasses import replace as dc_replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for p in (str(REPO / "src"), str(HERE.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from neutral_types import (BackendResult, BackendWitness, NeutralAtom,
                           NeutralCoreInput, PrimitiveResult, WorldResult)

from guardian_truth.vnext.integrity import canonical, digest
from guardian_truth.vnext.ledger import EvidenceLedger, LedgerIndex
from guardian_truth.vnext.proof_records import AtomKind, Obligation, ProofAtom, TimeMode
from guardian_truth.vnext.tools import (ConditionalGuarantee, ContractRegistry,
                                  EffectSpec, TrustedContract, evaluate_t1)
from guardian_truth.vnext.types import CoreStatus, EntityRef, LedgerEvent, Span, ToolIdentity, Truth
from guardian_truth.vnext.e2e.e2e_types_v1 import (FULL_SEMANTICS,
                                                   ReadingOption, UnresolvedMarker)
from guardian_truth.vnext.proof_records import InterpretationAxis
from guardian_truth.vnext.e2e.world_integration_v1 import (Component,
                                                           build_worlds,
                                                           make_problem,
                                                           prove_e2e_atom,
                                                           solve_e2e)

ACTION_KINDS = ("ACTION_ATTEMPTED", "ACTION_COMPLETED", "ACTION_FAILED")
STATE_KINDS = ("STATE_OBSERVATION", "FIELD_VALUE")

NEUTRAL_PROVIDER = "neutral-core-bakeoff"
NEUTRAL_VERSION = "1"


def _json(value) -> str:
    return canonical(value).decode("utf-8")


def _identity(name: str) -> ToolIdentity:
    return ToolIdentity(name, NEUTRAL_PROVIDER, NEUTRAL_VERSION,
                        digest({"tool": name})[:64])


def _reader_contract(tool: str, predicates: tuple[str, ...]) -> TrustedContract:
    return TrustedContract(
        identity=_identity(tool), preconditions=(), reads=tuple(predicates),
        writes=(), guarantees=(), possible_effects=(), no_effect_conditions=(),
        failure_semantics="no-effect-on-failure", freshness="fresh-read",
        idempotence="read", provenance="neutral-bakeoff-synthetic-contract")


def _writer_contract(tool: str, entity_field: str,
                     specs: tuple[EffectSpec, ...]) -> TrustedContract:
    return TrustedContract(
        identity=_identity(tool), preconditions=(), reads=(),
        writes=tuple(sorted({spec.predicate for spec in specs})),
        guarantees=(ConditionalGuarantee((), specs),), possible_effects=(),
        no_effect_conditions=(), failure_semantics="no-effect-on-failure",
        freshness="stale", idempotence="irrelevant",
        provenance="neutral-bakeoff-synthetic-contract")


class _Unit:
    """One fact group -> one (call, result) ledger event pair (or a text
    event for inert rows)."""
    __slots__ = ("facts", "kind", "min_index", "first_id", "tool", "contract",
                 "call_payload", "result_payload", "effect_specs")

    def __init__(self, facts, kind):
        self.facts = list(facts)
        self.kind = kind
        self.min_index = min((f.event_index for f in self.facts), default=0)
        self.first_id = self.facts[0].fact_id if self.facts else ""

    @property
    def region(self):
        return next((f.region for f in self.facts if f.region == "target"),
                    "history")


def _build_units(ci: NeutralCoreInput) -> list[_Unit]:
    units: list[_Unit] = []
    by_call: dict[str, _Unit] = {}
    # action facts grouped by call id
    for f in ci.facts:
        if f.kind in ACTION_KINDS:
            key = f"call:{f.call_id or f.fact_id}"
            if key not in by_call:
                by_call[key] = _Unit([], "action")
                units.append(by_call[key])
            by_call[key].facts.append(f)
    # observations grouped by (event_index, entity): one material snapshot
    obs_groups: dict[tuple[int, str], list] = {}
    for f in ci.facts:
        if f.kind in STATE_KINDS:
            key = (f.event_index, f.entity)
            obs_groups.setdefault(key, []).append(f)
    for key, group in obs_groups.items():
        units.append(_Unit(group, "obs"))
    # effects attach to their call unit when present
    for f in ci.facts:
        if f.kind == "EFFECT":
            key = f"call:{f.call_id}" if f.call_id else None
            if key and key in by_call:
                by_call[key].facts.append(f)
            else:
                units.append(_Unit([f], "effect"))
    # inert rows
    for f in ci.facts:
        if f.kind in ("CLAIM", "ENTITY", "RELATION"):
            units.append(_Unit([f], "text"))
    units.sort(key=lambda u: (u.min_index, u.first_id))
    return units


class _LedgerBundle:
    def __init__(self, ledger: EvidenceLedger, registry: ContractRegistry,
                 events: list[LedgerEvent], fact_units: dict[str, _Unit],
                 unit_events: dict[int, tuple[int, int]],
                 t2l: dict[int, int], max_t: int):
        self.ledger = ledger
        self.registry = registry
        self.events = events
        self.fact_units = fact_units            # fact_id -> unit
        self.unit_events = unit_events          # id(unit) -> (call_pos, result_pos)
        self.t2l = t2l                          # neutral event_index -> ledger pos
        self.max_t = max_t                      # last neutral event index (0 if none)

    def position_of_fact(self, fact) -> int:
        unit = self.fact_units[fact.fact_id]
        call_pos, result_pos = self.unit_events[id(unit)]
        return result_pos if unit.kind in ("action", "effect") else result_pos

    def call_position_of_fact(self, fact) -> int:
        unit = self.fact_units[fact.fact_id]
        return self.unit_events[id(unit)][0]

    def neutral_to_ledger(self, t: int) -> int:
        if t >= 10**9:
            return len(self.events) - 1
        return self.t2l.get(t, self._fallback_t2l(t))

    def _fallback_t2l(self, t: int) -> int:
        best = -1
        for nt in sorted(self.t2l):
            if nt <= t:
                best = self.t2l[nt]
            else:
                break
        return best if best >= 0 else 0


def build_ledger(ci: NeutralCoreInput) -> _LedgerBundle:
    units = _build_units(ci)
    contracts: list[TrustedContract] = []
    events: list[LedgerEvent] = []
    unit_events: dict[int, tuple[int, int]] = {}
    fact_units: dict[str, _Unit] = {}
    for u in units:
        for f in u.facts:
            fact_units[f.fact_id] = u

    for u in units:
        k = len(events)
        entity = next((f.entity for f in u.facts if f.entity != "*"), "*")
        entity_refs = (EntityRef("entity", entity),) if entity != "*" else ()
        doc = "response" if u.region == "target" else "prompt"
        if u.kind == "text":
            f = u.facts[0]
            events.append(LedgerEvent(
                f"ev{k}", k, "system" if f.actor in ("", "unknown") else f.actor,
                "text", Span(doc, k, k + 1), f.fact_id, None, None, None, (),
                None, None, entity_refs, None))
            unit_events[id(u)] = (k, k)
            continue
        if u.kind == "obs":
            tool = f"read_state_{k}"
            predicates = tuple(sorted({f.predicate for f in u.facts}))
            payload: dict = {}
            effect_specs: list[EffectSpec] = []
            for f in u.facts:
                if f.predicate not in payload:
                    payload[f.predicate] = f.value
                else:
                    # same-snapshot contradiction: second value materialized
                    # as a trusted effect on the SAME result event (the
                    # incumbent's only same-position contradiction shape)
                    effect_specs.append(EffectSpec("entity", f.predicate,
                                                   _json(f.value), False))
            contract = _reader_contract(tool, predicates)
            if effect_specs:
                contract = dc_replace(
                    contract,
                    guarantees=(ConditionalGuarantee((), tuple(effect_specs)),))
            contracts.append(contract)
            call = LedgerEvent(
                f"ev{k}", k, u.facts[0].actor, "call", Span(doc, k, k + 1),
                u.facts[0].fact_id, _json({"entity": entity}), _identity(tool),
                f"neutral-{k}", (), u.facts[0].actor, None, entity_refs, None)
            result = LedgerEvent(
                f"ev{k+1}", k + 1, "tool", "result", Span(doc, k + 1, k + 2),
                u.facts[0].fact_id, _json(payload), _identity(tool),
                f"neutral-{k}", (f"neutral-{k}",), u.facts[0].actor, None,
                entity_refs, None)
            events.extend((call, result))
            unit_events[id(u)] = (k, k + 1)
            continue
        # action / effect units: call + result (+ writer contract)
        action_fact = next((f for f in u.facts if f.kind in ACTION_KINDS), None)
        tool_name = action_fact.predicate if action_fact else f"mutate_{u.facts[0].predicate}"
        tool = _identity(tool_name)
        specs: list[EffectSpec] = []
        for f in u.facts:
            if f.kind == "EFFECT":
                specs.append(EffectSpec("entity", f.predicate, _json(f.value), True))
            elif f.kind == "ACTION_COMPLETED":
                specs.append(EffectSpec("entity", "done", "true", True))
        result_payload = {"op": "done"} if specs else (
            {"op": "error"} if any(f.kind == "ACTION_FAILED" for f in u.facts)
            else {"op": "ok"})
        if specs:
            contracts.append(_writer_contract(tool_name, "entity", tuple(specs)))
        call_payload = {"entity": entity}
        if action_fact is not None and action_fact.value is not None:
            call_payload["arg"] = action_fact.value
        call = LedgerEvent(
            f"ev{k}", k, (action_fact or u.facts[0]).actor, "call",
            Span(doc, k, k + 1), u.facts[0].fact_id, _json(call_payload), tool,
            f"neutral-{k}", (), (action_fact or u.facts[0]).actor, None,
            entity_refs, None)
        result = LedgerEvent(
            f"ev{k+1}", k + 1, "tool", "result", Span(doc, k + 1, k + 2),
            u.facts[0].fact_id, _json(result_payload), tool, f"neutral-{k}",
            (f"neutral-{k}",), (action_fact or u.facts[0]).actor, None,
            entity_refs, None)
        events.extend((call, result))
        unit_events[id(u)] = (k, k + 1)

    ledger = EvidenceLedger.from_events(
        tuple(events), history_complete=ci.history_complete,
        completeness_basis=ci.completeness_basis)
    # materialize effects through the incumbent's own T1 machinery
    effects = []
    real_registry = ContractRegistry(tuple(contracts))
    for u in units:
        if u.kind in ("action", "effect", "obs"):
            call_pos, result_pos = unit_events[id(u)]
            if call_pos == result_pos:
                continue
            value = evaluate_t1(real_registry, ledger.events[call_pos],
                                ledger.events[result_pos])
            effects.extend(value.effects)
    ledger = dc_replace(ledger, effects=tuple(effects))

    t2l: dict[int, int] = {}
    for u in units:
        last_pos = unit_events[id(u)][1]
        for f in u.facts:
            t2l[f.event_index] = max(t2l.get(f.event_index, -1), last_pos)
    max_t = max((f.event_index for f in ci.facts), default=0)
    return _LedgerBundle(ledger, ContractRegistry(tuple(contracts)), events,
                         fact_units, unit_events, t2l, max_t)


# ------------------------------------------------------------- atom lowering

def _prereq_atom(atom: NeutralAtom, bound: int, negate: bool) -> ProofAtom:
    """Condition leaf -> incumbent prerequisite atom (deterministic action
    path for attempted, conservative current-state path for state)."""
    if atom.kind == "attempted":
        expected = "false" if negate else "true"
        return ProofAtom(
            f"pa:{atom.atom_id}:{bound}", AtomKind.CALL_ATTEMPTED,
            EntityRef("prerequisite", atom.entity, "e2e"), atom.action,
            expected, atom.actor, TimeMode.THROUGH, bound)
    if atom.kind in ("state", "state_hist"):
        # incumbent convention: a negated condition atom flips the BOOLEAN
        # expectation; a value-typed atom under negation therefore compares
        # against `false` and (type mismatch) stays UNKNOWN — the incumbent's
        # honest abstention on value-typed exceptions, preserved here.
        expected = "false" if negate else _json(atom.expected)
        return ProofAtom(
            f"ps:{atom.atom_id}:{bound}", AtomKind.OBSERVED_STATE,
            EntityRef("entity", atom.entity), atom.predicate, expected,
            None, TimeMode.LATEST_OBSERVATION, bound)
    if atom.kind == "state_hist":
        expected = _json(not atom.expected) if negate else _json(atom.expected)
        return ProofAtom(
            f"ph:{atom.atom_id}:{bound}", AtomKind.OBSERVED_STATE,
            EntityRef("entity", atom.entity), atom.predicate, expected,
            None, TimeMode.THROUGH, bound)
    raise ValueError(f"unrepresentable condition leaf {atom.kind}")


def _lower_conditions(node, bound: int, sink: list, markers: list,
                      negate: bool = False) -> None:
    """Condition tree -> prerequisite atoms + unresolved markers.  Following
    the incumbent's binding discipline, a rule containing a leaf the program
    space cannot represent yields unresolved TERMS on the whole rule (never
    an approximation): the caller checks `markers_touched` and drops the
    rule's obligations (marker replaces them)."""
    if node is None:
        return True
    if node.atom is not None:
        if node.atom.kind in ("comparison", "cardinality"):
            markers.append((f"term:{node.atom.key()}:unrepresentable",
                            f"no incumbent primitive for {node.atom.kind} atom"))
            return False
        sink.append(_prereq_atom(node.atom, bound, negate))
        return True
    if node.not_ is not None:
        return _lower_conditions(node.not_, bound, sink, markers, not negate)
    if node.all_ is not None:
        ok = True
        for child in node.all_:
            ok = _lower_conditions(child, bound, sink, markers, negate) and ok
        return ok
    if node.any_ is not None:
        # incumbent policy conditions are a flat conjunction; disjunction is
        # 'not expressible in V1 program space' (compile_h0 / GRS CHOICE)
        for child in node.any_:
            _lower_conditions(child, bound, sink, markers, negate)
        markers.append((f"term:disjunction:{id(node)}",
                        "condition disjunction not expressible in V1 policy lowering"))
        return False
    raise ValueError("empty condition node")


def _temporal_conditions(rule, bound: int, sink: list, markers: list) -> None:
    if rule.temporal in ("BEFORE", "UNTIL"):
        # target may only fire once the anchor has happened: antecedent
        # includes NOT attempted(anchor) <= bound
        sink.append(_prereq_atom(NeutralAtom(
            f"anchor:{rule.temporal_anchor_action}", "attempted",
            action=rule.temporal_anchor_action, entity=rule.temporal_anchor_entity,
            actor="assistant", time_index=-1), bound, negate=True))
    elif rule.temporal == "AFTER":
        sink.append(_prereq_atom(NeutralAtom(
            f"anchor:{rule.temporal_anchor_action}", "attempted",
            action=rule.temporal_anchor_action, entity=rule.temporal_anchor_entity,
            actor="assistant", time_index=-1), bound, negate=False))


# ------------------------------------------------------------------ backend

def evaluate(ci: NeutralCoreInput) -> BackendResult:
    started = time.perf_counter()
    bundle = build_ledger(ci)
    ledger, registry = bundle.ledger, bundle.registry

    options: dict[str, ReadingOption] = {}
    for interp in ci.interpretations:
        obligations: list[Obligation] = []
        markers: list[tuple[str, str]] = []
        for marker in interp.unresolved:
            markers.append((f"interp:{interp.interp_id}:{marker}", marker))
        last_bound = bundle.neutral_to_ledger(bundle.max_t)
        for rule in interp.rules:
            targets = [f for f in ci.facts
                       if f.region == "target" and f.kind in ACTION_KINDS
                       and f.predicate == rule.action
                       and (rule.entity == "*" or f.entity == rule.entity)
                       and f.actor == rule.actor]
            if rule.modality == "FORBID":
                if not targets:
                    continue        # vacuously satisfied (incumbent convention)
                # incumbent binding discipline: a rule with an unrepresentable
                # condition leaf keeps its unresolved terms and gets NO
                # obligations (the marker replaces the rule)
                probe_conds, probe_markers = [], []
                representable = _lower_conditions(rule.conditions, 0,
                                                  probe_conds, probe_markers)
                for exc in rule.exceptions:
                    representable = _lower_conditions(exc, 0, [], probe_markers,
                                                      negate=True) and representable
                if not representable:
                    markers.append((f"rule:{rule.rule_id}:unrepresentable",
                                    "rule has unrepresentable condition terms"))
                    continue
                for f in targets:
                    call_pos = bundle.call_position_of_fact(f)
                    result_pos = bundle.position_of_fact(f)
                    if rule.target_level == "ATTEMPT":
                        atom = ProofAtom(
                            f"{rule.rule_id}:{f.fact_id}:t", AtomKind.TARGET_CALL_MATCH,
                            EntityRef("event_id", bundle.events[call_pos].event_id,
                                      "ledger"), rule.action, "true", rule.actor,
                            TimeMode.AT, call_pos, call_id=bundle.events[call_pos].call_id)
                        cond_bound = max(call_pos - 1, 0)
                    else:
                        if rule.entity == "*":
                            markers.append((f"term:{rule.rule_id}:completed-wildcard",
                                            "completed-level wildcard entity not representable"))
                            continue
                        atom = ProofAtom(
                            f"{rule.rule_id}:{f.fact_id}:c", AtomKind.ACTION_COMPLETED,
                            EntityRef("entity", f.entity), rule.action, "true",
                            rule.actor, TimeMode.THROUGH, result_pos)
                        cond_bound = max(call_pos - 1, 0)
                    conds: list[ProofAtom] = []
                    _lower_conditions(rule.conditions, cond_bound, conds, markers)
                    for exc in rule.exceptions:
                        _lower_conditions(exc, cond_bound, conds, markers, negate=True)
                    _temporal_conditions(rule, cond_bound, conds, markers)
                    obligations.append(Obligation(
                        f"{rule.rule_id}::{f.fact_id}", rule.rule_id, None, atom,
                        False, tuple(conds)))
            else:   # REQUIRE
                probe_conds, probe_markers = [], []
                representable = _lower_conditions(rule.conditions, 0,
                                                  probe_conds, probe_markers)
                for exc in rule.exceptions:
                    representable = _lower_conditions(exc, 0, [], probe_markers,
                                                      negate=True) and representable
                if not representable:
                    markers.append((f"rule:{rule.rule_id}:unrepresentable",
                                    "rule has unrepresentable condition terms"))
                    continue
                bound = last_bound
                if rule.target_level == "ATTEMPT":
                    atom = ProofAtom(
                        f"{rule.rule_id}:hist", AtomKind.HISTORICAL_ACTION,
                        EntityRef("resource", rule.entity, "e2e"), rule.action,
                        "true", rule.actor, TimeMode.THROUGH, bound)
                else:
                    if rule.entity == "*":
                        markers.append((f"term:{rule.rule_id}:completed-wildcard",
                                        "completed-level wildcard entity not representable"))
                        continue
                    atom = ProofAtom(
                        f"{rule.rule_id}:comp", AtomKind.ACTION_COMPLETED,
                        EntityRef("entity", rule.entity), rule.action, "true",
                        rule.actor, TimeMode.THROUGH, bound)
                conds: list[ProofAtom] = []
                _lower_conditions(rule.conditions, bound, conds, markers)
                for exc in rule.exceptions:
                    _lower_conditions(exc, bound, conds, markers, negate=True)
                _temporal_conditions(rule, bound, conds, markers)
                obligations.append(Obligation(
                    f"{rule.rule_id}::exist", rule.rule_id, None, atom, True,
                    tuple(conds)))
        options[interp.interp_id] = ReadingOption(
            interp.interp_id, tuple(obligations), (),
            tuple(UnresolvedMarker(mid, reason) for mid, reason in markers))

    axis = InterpretationAxis("interp", tuple(options),
                              f"neutral-interpretations:{ci.case_id}", True)
    component = Component(axis, options)
    worlds, required, budget_exceeded = build_worlds((component,), max_worlds=4096)
    problem = make_problem((component,), worlds)
    result = solve_e2e(problem, ledger, registry, FULL_SEMANTICS)

    # ---- normalize the incumbent's result into the backend contract
    world_results = tuple(
        WorldResult(proof.choices[0] if proof.choices else w.world_id,
                    _truth_str(proof.error_value),
                    tuple((oid, _truth_str(value)) for oid, value in proof.obligation_safety))
        for w, proof in zip(problem.worlds, result.world_proofs))

    index = LedgerIndex(ledger)
    witnesses = _extract_witnesses(problem, result, bundle)
    runtime_ms = (time.perf_counter() - started) * 1000.0
    notes = []
    if budget_exceeded:
        notes.append(f"WORLD_BUDGET_EXCEEDED:{required}")
    return BackendResult(
        backend="current_guardian", status=result.status.value,
        worlds=world_results, primitives=(), witnesses=witnesses,
        runtime_ms=runtime_ms, input_content_hash=ci.content_hash(),
        notes="; ".join(notes))


def probe(ci: NeutralCoreInput, atoms: list[NeutralAtom]) -> list[PrimitiveResult]:
    bundle = build_ledger(ci)
    ledger, registry = bundle.ledger, bundle.registry
    index = LedgerIndex(ledger)
    out = []
    for atom in atoms:
        bound = bundle.neutral_to_ledger(atom.time_index)
        if atom.kind == "attempted":
            pa = ProofAtom(f"probe:{atom.key()}", AtomKind.CALL_ATTEMPTED,
                           EntityRef("prerequisite", atom.entity, "e2e"),
                           atom.action, "true", atom.actor, TimeMode.THROUGH, bound)
        elif atom.kind == "completed":
            if atom.entity == "*":
                out.append(PrimitiveResult(atom.key(), "UNKNOWN", (), ()))
                continue
            pa = ProofAtom(f"probe:{atom.key()}", AtomKind.ACTION_COMPLETED,
                           EntityRef("entity", atom.entity), atom.action, "true",
                           atom.actor, TimeMode.THROUGH, bound)
        elif atom.kind == "state":
            pa = ProofAtom(f"probe:{atom.key()}", AtomKind.OBSERVED_STATE,
                           EntityRef("entity", atom.entity), atom.predicate,
                           _json(atom.expected), None, TimeMode.LATEST_OBSERVATION,
                           bound)
        elif atom.kind == "state_hist":
            pa = ProofAtom(f"probe:{atom.key()}", AtomKind.OBSERVED_STATE,
                           EntityRef("entity", atom.entity), atom.predicate,
                           _json(atom.expected), None, TimeMode.THROUGH, bound)
        else:
            # comparison / cardinality: no incumbent primitive — surfaced
            # honestly as UNKNOWN (probe level), like the lowering markers
            out.append(PrimitiveResult(atom.key(), "UNKNOWN", (), ()))
            continue
        proof = prove_e2e_atom(pa, ledger, index, registry, FULL_SEMANTICS)
        supports = tuple(_fact_of_event(eid, bundle) for eid in proof.supports)
        refutes = tuple(_fact_of_event(eid, bundle) for eid in proof.refutes)
        out.append(PrimitiveResult(atom.key(), _truth_str(proof.value),
                                   supports, refutes))
    return out


def _truth_str(value: Truth) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _fact_of_event(event_id: str, bundle: _LedgerBundle) -> str:
    """Map a ledger evidence id back to the originating neutral fact id."""
    if event_id.startswith("obs:") or event_id.startswith("t1:") \
            or event_id.startswith("possible:") or event_id.startswith("absence:"):
        # obs:<event_id>:<hash> / t1:<event_id>:<i>
        parts = event_id.split(":")
        ev = parts[1] if len(parts) > 2 else event_id
    else:
        ev = event_id
    try:
        pos = int(ev[2:]) if ev.startswith("ev") else None
    except ValueError:
        pos = None
    if pos is not None and 0 <= pos < len(bundle.events):
        return bundle.events[pos].raw_text or event_id
    return event_id


def _extract_witnesses(problem, result, bundle: _LedgerBundle):
    witnesses = []
    for world, proof in zip(problem.worlds, result.world_proofs):
        for obligation_id, value in proof.obligation_safety:
            rule_id = obligation_id.split("::")[0]
            supports, refutes, unknowns = [], [], []
            for primitive in proof.primitives:
                for eid in primitive.supports:
                    supports.append(_fact_of_event(eid, bundle))
                for eid in primitive.refutes:
                    refutes.append(_fact_of_event(eid, bundle))
                if primitive.value in (Truth.UNKNOWN, Truth.BOTH):
                    unknowns.extend(r.value for r in primitive.reasons)
            witnesses.append(BackendWitness(
                rule_id=rule_id,
                interpretation_id=world.choices[0] if world.choices else "",
                conclusion=_truth_str(value),
                supporting_fact_ids=tuple(dict.fromkeys(supports)),
                refuting_fact_ids=tuple(dict.fromkeys(refutes)),
                unknown_dependencies=tuple(dict.fromkeys(unknowns))[:8],
                engine_native_explanation=f"incumbent WorldProof {world.world_id} "
                                          f"obligation {obligation_id}"))
    return tuple(witnesses)

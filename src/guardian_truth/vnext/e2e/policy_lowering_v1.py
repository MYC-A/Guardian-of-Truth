"""Policy lowering V1: compiled v3 programs + bindings -> Core obligations.

The v3 program space (policy_v3_benchmark.evaluate_v3_program) is the frozen
behavioral contract of BOTH policy frontends.  This module lowers each
compiled program (rule) into baseline ProofObligations such that the solver's
material implication reproduces the v3 verdict composition on the
trajectory-evidence surface.

ENCODINGS (all inside the baseline proof language — no solver changes):

  match(e,T,checks)   TARGET_CALL_MATCH atom: event e is a call to tool T
                      with the argument checks (attempt level).
  NOT-match(e,T,...)  the same atom with expected_json "false".
  sentinel            TARGET_CALL_MATCH with the reserved predicate
                      "goal:unaddressed" over a real target-call witness
                      event: determinately FALSE (no tool can carry the
                      reserved "goal:" prefix; the case validator enforces it).

  Direct prohibition (no exceptions):
      Obligation(match, must_be_true=False, conditions=[gate atoms...])
      safety = NOT gate OR NOT match            (violation = match AND gate)
  Disarming pattern (exceptions / ONLY_IF gates):
      Obligation(disarmer, must_be_true=True, conditions=[match, *gate])
      safety = NOT (match AND gate) OR disarmer
      One obligation per exception/gate literal; their conjunction gives
      'if match AND gate then ALL disarmers must hold'.
  Requirement 'X must happen' (at-least-once):
      Obligation(sentinel, must_be_true=True,
                 conditions=[*gate, NOT-match(e,X) for every target call e])
      safety = some call to X exists (or the gate fails) — zero target calls
      keeps an unresolved marker (nothing was attempted at all).

  VERBATIM EQUIVALENCE with evaluate_v3_program:
      PROHIBITION IF/ONLY_IF/IFF   violation = triggered AND conds AND NOT excs
      PROHIBITION UNLESS/UNCOND    violation = triggered AND NOT excs
      REQUIREMENT UNCONDITIONAL    violation = NOT triggered
      REQUIREMENT IF               violation = conds AND NOT triggered
      REQUIREMENT ONLY_IF/IFF      violation = triggered AND NOT conds
      REQUIREMENT UNLESS           violation = NOT excs AND NOT triggered
      PERMISSION ONLY_IF/IFF       violation = triggered AND NOT conds AND NOT excs
      PERMISSION otherwise         no obligation (permission is not obligation)

  OUTSIDE THE E2E V1 ENVELOPE (honest unresolved markers, never silent):
      - ANY-mode gates/exceptions with >= 2 literals (disjunctive evidence)
      - PERMISSION exclusivity combining gates AND exceptions
      - cross-tool together-clauses (same-event conjunction only)
      - together-clauses split across different events
      - REQUIREMENT with zero target calls (nothing attempted)

Everything here is deterministic: no LLM, no network, no wall-clock.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..integrity import canonical
from ..proof_records import ArgumentConstraint, AtomKind, Obligation, ProofAtom, TimeMode
from ..types import EntityRef, Reason
from .goal_types_v1 import AtomBindingCandidate, BindingLevel, BindingRecord

RESERVED_PREDICATE_PREFIX = "goal:"
UNADDRESSED_SENTINEL = "goal:unaddressed"


@dataclass(frozen=True)
class LoweringContext:
    """Deterministic trajectory facts the lowering reads (never gold).

    target_calls: assistant calls in the RESPONSE document (the judged action).
    all_calls: every call event in the ledger (history + target), for the
    deterministic at-least-once scan and temporal guards.
    """

    target_calls: tuple[dict, ...]        # {event_id, index, call_id, tool, arguments, actor}
    end_index: int
    all_calls: tuple[dict, ...] = ()

    def witness(self) -> dict | None:
        return self.target_calls[0] if self.target_calls else None

    def scan_satisfying_call(self, tool: str, checks=()) -> dict | None:
        """Deterministic ledger scan: the first assistant call to `tool`
        matching all argument checks anywhere in the ledger.  The scan reads
        the same append-only ledger the prover and the certificate checker
        re-verify, so the decision is tamper-evident and re-derivable."""
        for event in self.all_calls:
            if event.get("tool") != tool or event.get("actor") != "assistant":
                continue
            if _checks_match(event.get("arguments") or {}, checks):
                return event
        return None


def _checks_match(arguments: dict, checks) -> bool:
    from ..integrity import canonical
    for check in checks:
        actual = arguments
        for key in check.path:
            if not isinstance(actual, dict) or key not in actual:
                return False
            actual = actual[key]
        if check.presence_only:
            continue
        if canonical(actual).decode("utf-8") not in check.allowed_json:
            return False
    return True


@dataclass(frozen=True)
class LoweredChoice:
    choice_id: str
    obligations: tuple[Obligation, ...]
    unresolved_reasons: tuple[Reason, ...]
    audit: tuple[tuple[str, str], ...]


# ------------------------------------------------------------------- atoms

def _constraints(checks) -> tuple[ArgumentConstraint, ...]:
    return tuple(ArgumentConstraint(tuple(check.path), tuple(check.allowed_json),
                                    check.presence_only) for check in checks)


def _match_atom(event: dict, tool: str, checks, *, expected: str = "true") -> ProofAtom:
    return ProofAtom(f"match:{event['event_id']}:{tool}:{len(checks)}:{expected}",
                     AtomKind.TARGET_CALL_MATCH,
                     EntityRef("event_id", event["event_id"], "ledger"),
                     tool, expected, "assistant", TimeMode.AT, event["index"],
                     event.get("call_id"), argument_constraints=_constraints(checks))


def _sentinel_atom(context: LoweringContext) -> ProofAtom | None:
    witness = context.witness()
    if witness is None:
        return None
    return ProofAtom("sentinel:" + witness["event_id"], AtomKind.TARGET_CALL_MATCH,
                     EntityRef("event_id", witness["event_id"], "ledger"),
                     UNADDRESSED_SENTINEL, "true", "assistant", TimeMode.AT,
                     witness["index"], witness.get("call_id"))


def _state_atom(observation, entity: EntityRef, time_index: int, expected: str) -> ProofAtom:
    predicate = ".".join(observation.path)
    return ProofAtom(f"state:{entity.key}:{entity.value}:{predicate}", AtomKind.OBSERVED_STATE,
                     entity, predicate, expected, None, TimeMode.LATEST_OBSERVATION, time_index)


def _event_atom(candidate: AtomBindingCandidate, entity: EntityRef | None, time_index: int,
                *, expected: str = "true") -> ProofAtom:
    """Event evidence atom.  A CATALOG_IDENTITY candidate (repair A3) has no
    entity path — it uses the E2E V1 wildcard entity (any assistant call to
    the tool), which can only under-trigger, never over-trigger."""
    if entity is None:
        entity = EntityRef("any", "*", "wildcard")
    return ProofAtom(f"event:{candidate.tool}:{entity.value}", AtomKind.CALL_ATTEMPTED,
                     entity, candidate.tool, expected, "assistant", TimeMode.THROUGH, time_index)


def _not_called_atom(tool: str, end_index: int, *, expected: str = "false") -> ProofAtom:
    """'no assistant call to tool T anywhere in the ledger' — a CALL_ATTEMPTED
    atom with the reserved wildcard entity namespace (E2E V1 additive).  Proven
    FALSE when such a call exists; TRUE only under absence verification
    (closed action universe + complete history); UNKNOWN otherwise."""
    return ProofAtom(f"notcalled:{tool}", AtomKind.CALL_ATTEMPTED,
                     EntityRef("any", "*", "wildcard"), tool, expected, "assistant",
                     TimeMode.THROUGH, end_index)


def _entity_for(event: dict, candidate: AtomBindingCandidate) -> EntityRef | None:
    """Deterministic entity identity for state/event evidence atoms: the
    argument value at the candidate's entity path, read from the actual
    target call.  Returns None when the action is not entity-scoped."""
    entity_path = candidate.entity_path
    if not entity_path and candidate.observation is not None:
        entity_path = candidate.observation.entity_path
    if not entity_path:
        return None
    value = event.get("arguments") or {}
    for key in entity_path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    if type(value) not in {str, int}:
        return None
    return EntityRef(".".join(entity_path), str(value), "source")


# ---------------------------------------------------------------- lowering

class _RuleLowering:
    """Per-(reading, binding, event) lowering state."""

    def __init__(self, program: dict, binding: BindingRecord, context: LoweringContext,
                 prefix: str, counter: list):
        self.program = program
        self.binding = binding
        self.context = context
        self.prefix = prefix
        self.counter = counter
        self.obligations: list[Obligation] = []
        self.unresolved: list[Reason] = []
        self.audit: list[tuple[str, str]] = []
        self.failures: list[str] = []
        self.actor_exclusive = False
        self.actor_inapplicable = False
        self.actor_literal = None

    def _next_id(self) -> str:
        self.counter[0] += 1
        return f"{self.prefix}:o{self.counter[0]}"

    # -- gate/exception literal -> (state atoms, structural flags) --

    def _literal_atoms(self, literals, event, label) -> tuple[list[ProofAtom], bool]:
        """Resolve gate/exception literals to provable condition atoms.
        Returns (atoms, ok).  Actor literals are structural: assistant role
        is satisfied by construction for assistant target calls; other roles
        mark the rule inapplicable-but-unresolved (never silently dropped)."""
        atoms, ok = [], True
        for literal in literals:
            negated = literal.startswith("!")
            atom_name = literal[1:] if negated else literal
            kind = atom_name.split(":", 1)[0]
            candidates = self.binding.atom_candidates(atom_name)
            if kind == "actor":
                role = candidates[0].actor_role if candidates else "assistant"
                if role != "assistant":
                    # the constraint names a DIFFERENT actor than the assistant.
                    # Exclusive shapes (ONLY_IF/IFF) make non-X actions violations;
                    # applicability shapes make the rule inapplicable to assistant
                    # calls (USER_ACTION != ASSISTANT_ACTION).
                    self.actor_exclusive = (label == "gate"
                                            and self.program["relation"] in
                                            {"ONLY_IF", "IF_AND_ONLY_IF"})
                    self.actor_inapplicable = not self.actor_exclusive
                    self.actor_literal = atom_name
                continue
            if not candidates:
                self.failures.append(f"{self.prefix}:{label}_unbound:{atom_name}")
                ok = False
                continue
            candidate = candidates[0]
            if kind == "state" and candidate.observation is not None:
                entity = _entity_for(event, candidate) or EntityRef("state", atom_name, "semantic")
                expected = candidate.observation.expected_json
                if negated:
                    # negated literals (compiled BEFORE gates '!event:E') invert
                    # the expectation; non-boolean negation is outside the envelope
                    parsed = _parse_json(expected)
                    if not isinstance(parsed, bool):
                        self.failures.append(f"{self.prefix}:{label}_negated_nonboolean:{atom_name}")
                        ok = False
                        continue
                    expected = "false" if parsed else "true"
                atoms.append(_state_atom(candidate.observation, entity, event["index"], expected))
            elif kind == "event":
                entity = _entity_for(event, candidate)
                if entity is None and candidate.level is not BindingLevel.CATALOG_IDENTITY:
                    self.failures.append(f"{self.prefix}:{label}_event_entity_unbound:{atom_name}")
                    ok = False
                    continue
                atoms.append(_event_atom(candidate, entity, self.context.end_index,
                                         expected="false" if negated else "true"))
            else:
                self.failures.append(f"{self.prefix}:{label}_kind_unsupported:{atom_name}")
                ok = False
        return atoms, ok

    # -- main entry: lower one rule --

    def run(self) -> tuple[tuple[Obligation, ...], tuple[Reason, ...], tuple[tuple[str, str], ...]]:
        program = self.program
        modality, relation = program["modality"], program["relation"]
        clauses = program["target_clauses"]
        conds = program["condition_literals"]
        cond_mode = program["condition_mode"]
        excs = program["exception_literals"]
        exc_mode = program["exception_mode"]
        if cond_mode == "ANY" and len(conds) > 1:
            self.failures.append(f"{self.prefix}:disjunctive_gate_unsupported")
            self.unresolved.append(Reason.POLICY_OPEN_SEMANTICS)
        if exc_mode == "ANY" and len(excs) > 1:
            self.failures.append(f"{self.prefix}:disjunctive_exception_unsupported")
            self.unresolved.append(Reason.POLICY_OPEN_SEMANTICS)

        if self.actor_inapplicable or (self.actor_exclusive
                                       and modality in {"PROHIBITION", "REQUIREMENT"}):
            # the rule governs a DIFFERENT actor's actions; assistant target
            # calls can neither satisfy nor violate it (recorded, not dropped)
            self.failures.append(f"{self.prefix}:actor_inapplicable:{self.actor_literal}")
            self.audit.append((self.prefix + ":actor-inapplicable",
                               f"rule governed by non-assistant actor {self.actor_literal}"))
            return tuple(self.obligations), tuple(dict.fromkeys(self.unresolved)), tuple(self.audit)
        for event in self.context.target_calls:
            gate_atoms, gate_ok = self._literal_atoms(conds, event, "gate")
            if self.actor_exclusive:
                # 'only X may ...' with X != assistant: every assistant
                # occurrence of the target violates the exclusivity outright
                gate_atoms = []
            exc_atoms, exc_ok = self._literal_atoms(excs, event, "exception")
            # exception atoms are DISARMERS: they must HOLD for the rule to be
            # switched off, so their expectation is the binding's positive value
            # (already expected_json); the _literal_atoms negation handling above
            # applies only to '!'-prefixed literals.
            if not gate_ok or not exc_ok:
                self.unresolved.append(Reason.POLICY_OPEN_SEMANTICS)
                continue
            for clause in clauses:
                self._lower_clause(modality, relation, event, clause, gate_atoms, exc_atoms)
        if modality == "REQUIREMENT" and not self.context.target_calls:
            self.failures.append(f"{self.prefix}:requirement_no_target_calls")
            self.unresolved.append(Reason.EVIDENCE_INCOMPLETE)
        return tuple(self.obligations), tuple(dict.fromkeys(self.unresolved)), tuple(self.audit)

    def _clause_bindings(self, clause, event):
        bound = []
        for literal in clause:
            atom_name = literal[1:] if literal.startswith("!") else literal
            candidates = self.binding.atom_candidates(atom_name)
            if not candidates:
                self.failures.append(f"{self.prefix}:target_unbound:{atom_name}")
                return None
            bound.append((atom_name, candidates[0]))
        tools = {candidate.tool for _, candidate in bound}
        if len(bound) > 1 and len(tools) > 1:
            self.failures.append(f"{self.prefix}:together_clause_cross_tool")
            return None
        return bound

    def _lower_clause(self, modality, relation, event, clause, gate_atoms, exc_atoms):
        bound = self._clause_bindings(clause, event)
        if bound is None:
            self.unresolved.append(Reason.POLICY_OPEN_SEMANTICS)
            return
        for atom_name, candidate in bound:
            match = _match_atom(event, candidate.tool, candidate.argument_checks)
            others = tuple(_match_atom(event, other.tool, other.argument_checks)
                           for name, other in bound if name != atom_name)
            if modality == "PROHIBITION":
                if exc_atoms:
                    # disarming: if match AND gate then every exception must hold
                    for disarmer in exc_atoms:
                        self._add(disarmer, True, (*others, match, *gate_atoms),
                                  f"FORBID {atom_name} EXCEPT @ {event['event_id']}")
                else:
                    self._add(match, False, (*others, *gate_atoms),
                              f"FORBID {atom_name} @ {event['event_id']}")
            elif modality == "REQUIREMENT":
                self._lower_requirement(relation, event, atom_name, candidate,
                                        gate_atoms, exc_atoms, match, others)
            elif modality == "PERMISSION" and relation in {"ONLY_IF", "IF_AND_ONLY_IF"}:
                if exc_atoms:
                    self.failures.append(f"{self.prefix}:permission_gate_and_exception_unsupported")
                    self.unresolved.append(Reason.POLICY_OPEN_SEMANTICS)
                    return
                if self.actor_exclusive:
                    # 'only X may ...' with X != the assistant: the assistant
                    # occurrence violates the exclusivity outright
                    self._add(match, False, others,
                              f"PERMIT-EXCLUSIVE-ACTOR {atom_name} @ {event['event_id']}")
                    continue
                for disarmer in gate_atoms:
                    self._add(disarmer, True, (*others, match),
                              f"PERMIT-EXCLUSIVE {atom_name} @ {event['event_id']}")

    def _lower_requirement(self, relation, event, atom_name, candidate,
                           gate_atoms, exc_atoms, match, others):
        prefix = self.prefix
        if relation == "UNCONDITIONAL":
            self._require_at_least_once(atom_name, candidate, ())
        elif relation == "IF":
            self._require_at_least_once(atom_name, candidate, tuple(gate_atoms))
        elif relation in {"ONLY_IF", "IF_AND_ONLY_IF"}:
            if exc_atoms:
                self.failures.append(f"{prefix}:requirement_onlyif_and_exception_unsupported")
                self.unresolved.append(Reason.POLICY_OPEN_SEMANTICS)
                return
            if not gate_atoms:
                # no gate literal survived binding: outside envelope, keep open
                self.failures.append(f"{prefix}:requirement_onlyif_without_gate")
                self.unresolved.append(Reason.POLICY_OPEN_SEMANTICS)
                return
            for disarmer in gate_atoms:
                self._add(disarmer, True, (*others, match),
                          f"REQUIRE-ONLY-IF {atom_name} @ {event['event_id']}")
        elif relation == "UNLESS":
            if not exc_atoms:
                self.failures.append(f"{prefix}:requirement_unless_without_exception")
                self.unresolved.append(Reason.POLICY_OPEN_SEMANTICS)
                return
            satisfying = self.context.scan_satisfying_call(candidate.tool,
                                                           candidate.argument_checks)
            if satisfying is not None:
                self.audit.append((self.prefix + ":satisfied",
                                   f"REQUIRE-UNLESS {atom_name} satisfied by {satisfying['event_id']}"))
                return
            sentinel = _sentinel_atom(self.context)
            if sentinel is None:
                return
            target_not_matches = tuple(
                _match_atom(event, candidate.tool, candidate.argument_checks,
                            expected="false")
                for event in self.context.target_calls)
            if not target_not_matches:
                self.failures.append(f"{self.prefix}:require_unless_no_target_calls")
                return
            for disarmer in exc_atoms:
                self._add(disarmer, True, target_not_matches,
                          f"REQUIRE-UNLESS {atom_name} (scan: not done)")

    def _require_at_least_once(self, atom_name, candidate, gate_atoms):
        """REQUIRE X (at-least-once): if the deterministic ledger scan finds a
        satisfying call anywhere (history or target), the requirement is
        satisfied and NO obligation is emitted (audit records it).  Otherwise
        the violation is proved from per-target NOT-match atoms — every target
        call is provably not a call to X with the required arguments."""
        satisfying = self.context.scan_satisfying_call(candidate.tool,
                                                       candidate.argument_checks)
        if satisfying is not None:
            self.audit.append((self.prefix + ":satisfied",
                               f"REQUIRE {atom_name} satisfied by {satisfying['event_id']}"))
            return
        sentinel = _sentinel_atom(self.context)
        if sentinel is None:
            return  # zero target calls: the caller's marker governs
        target_not_matches = tuple(
            _match_atom(event, candidate.tool, candidate.argument_checks,
                        expected="false")
            for event in self.context.target_calls)
        if not target_not_matches:
            # no target calls at all: nothing proves the omission within the
            # envelope; the caller's marker governs
            return
        self._add(sentinel, True, (*gate_atoms, *target_not_matches),
                  f"REQUIRE {atom_name} at-least-once (scan: no satisfying call)")

    def _add(self, atom, must_be_true, conditions, description):
        """Emit one obligation: prove `atom` (must_be_true polarity) whenever
        the conjunctive `conditions` antecedent holds (material implication)."""
        oid = self._next_id()
        self.obligations.append(Obligation(oid, self.prefix, None, atom,
                                           must_be_true, tuple(conditions)))
        self.audit.append((oid, description))


def _parse_json(encoded: str):
    import json
    try:
        return json.loads(encoded)
    except (ValueError, TypeError):
        return None


def lower_policy_reading(reading, binding: BindingRecord,
                         context: LoweringContext) -> LoweredChoice:
    counter = [0]
    obligations, unresolved, audit = [], [], []
    for program in reading.programs:
        lowering = _RuleLowering(program, binding, context, reading.reading_id, counter)
        obs, unres, aud = lowering.run()
        obligations.extend(obs)
        unresolved.extend(unres)
        audit.extend(aud)
    return LoweredChoice(reading.reading_id, tuple(obligations),
                         tuple(dict.fromkeys(unresolved)), tuple(audit))

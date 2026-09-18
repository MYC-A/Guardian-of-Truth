"""core_engine_bakeoff_v1 — the ONE neutral Core input (experiment contract).

All backend adapters (current Guardian Core, Clingo, s(CASP), Drools) receive
structurally identical NeutralCoreInput objects; only the translation into
each engine's native representation may differ.  The NeutralCoreInput is the
experiment's analogue of what the incumbent E2E core receives AFTER its
frontends: already-structured facts (the evidence layer's classification of
the transcript) and already-formalized rule semantics (the Phi interpretations
lowered to deontic primitives).  No engine is asked to understand English.

======================================================================
REFERENCE SEMANTICS (the contract every backend must implement natively)
======================================================================
These are the current Guardian V1 core semantics, written representation-
free.  They are NOT renegotiated per engine: a backend that cannot express
one of them must surface it (UNKNOWN / unresolved marker), never silently
approximate it.

S1. Four-valued evidence.  Every query atom Q is evaluated to
    TRUE / FALSE / BOTH / UNKNOWN from SUPPORT and REFUTATION evidence:
      TRUE  : support(Q) nonempty, refute(Q) empty
      FALSE : refute(Q) nonempty, support(Q) empty
      BOTH  : both nonempty (same-position contradiction for state queries)
      UNKNOWN: neither (absence of evidence is NOT refutation)
    Closed-world reasoning is allowed ONLY under the explicit premise
    history_complete=True with no unknown-actor facts (Guardian's e2e
    absence proof for ATTEMPT-level queries); closed_action_universe is a
    recorded source declaration the attempt evaluator does not additionally
    gate on (matching the incumbent's deterministic action atom).

S2. Query atoms (NeutralAtom):
      attempted(action, entity, actor, t)  — an invocation of `action` on
          `entity` by `actor` at some event index <= t, in EITHER region
          (history or target; region is a lowering notion for FORBID
          targets, not a restriction on the atom query itself).  Evidence:
          matching ACTION_ATTEMPTED / ACTION_COMPLETED / ACTION_FAILED
          facts.  (A failed call still SUPPORTS attempted; it never supports
          completed.)  Absence of any matching fact is provable FALSE only
          under history_complete=True with no unknown-actor facts (the
          incumbent's e2e-namespace absence proof; the supplied trace is
          then the complete record of invocations).
      completed(action, entity, actor, t)  — a trusted completion.  Evidence:
          ACTION_COMPLETED facts (and EFFECT facts, whose causing action
          completed).  A failed call provides NEITHER support NOR refutation:
          completion stays UNKNOWN (open world; FAILED_CALL != SUCCESS, and
          absence of a trusted effect is not a proof of non-completion).
      state(entity, predicate, expected, LATEST, t) — CURRENT state value:
          evidence = STATE_OBSERVATION / FIELD_VALUE / trusted EFFECT facts
          with the same entity+predicate and index <= t.
          * if the LATEST evidence position carries both a matching and a
            mismatching value (one material snapshot): BOTH
          * if any attempted mutation of the entity sits AFTER the latest
            trusted evidence position and <= t: UNKNOWN (staleness is
            symmetric; an unproven mutation invalidates support AND
            refutation alike)
          * else the freshest evidence decides; older contrary evidence is
            superseded (historical, never BOTH)
          * no trusted evidence: UNKNOWN (an operation-status row or an
            uncontracted observation is not entity state — represented here
            by facts the evidence layer already classified as non-trusted)
      state_hist(entity, predicate, expected, t) — PAST existential value:
          TRUE iff ANY trusted evidence at index <= t showed the value;
          FALSE is NOT reachable (refuting 'never was X' needs the complete
          external state timeline, which history_complete does not certify).
      comparison(entity, predicate, op, literal) — numeric/typed comparison
          against the entity's CURRENT state value (LATEST semantics,
          including the mutation-invalidation rule of S2.state): TRUE if the
          value is known and the comparison holds, FALSE if known and it
          fails, UNKNOWN if the state is unknown, BOTH on a same-position
          contradiction.
      cardinality(subject, entity, actor, op, n, t) — count of DISTINCT
          matching events (attempted/completed facts or observations of the
          subject) with index <= t.  With history_complete=True the count is
          exact and the comparison is TRUE/FALSE.  Without complete history
          the count is a lower bound: AT_LEAST stays decidable (TRUE iff
          lower bound >= n, else UNKNOWN); AT_MOST/EXACTLY are UNKNOWN.

S3. Claims are not evidence.  CLAIM facts are carried in the input (they are
    part of the transcript's evidence-layer output) but NEVER support or
    refute S2 atoms.  ENTITY / RELATION facts are registry rows: they are
    inert for rule evaluation (documented noise channel — a backend must not
    promote them into actions or states).

S4. Rules (NeutralRule) lower to obligations exactly like the incumbent
    policy lowering (policy_lowering_v1 + grounding).  Evaluation bounds:
      * FORBID obligations are evaluated AT the target attempt event: the
        target atom (invocation match) is sampled at that event, while
        CONDITION/EXCEPTION atoms are evaluated THROUGH the position JUST
        BEFORE it — the gate's own act does not invalidate the state or the
        history it is judged against (an attempted mutation strictly between
        the latest trusted evidence and the gate still yields UNKNOWN).
      * REQUIRE obligations are evaluated THROUGH the last event index.
      FORBID @ ATTEMPT  — one obligation PER matching attempt fact in the
          TARGET region (the response under evaluation; the response document
          is complete, so absence of a matching target attempt fact means
          'not attempted in the response' — this one closed-world step is the
          incumbent's own and is sound for the artifact under audit).  With
          no matching target attempts the rule is vacuously satisfied.
          safety = NOT antecedent OR NOT target_atom  (material implication,
          four-valued connectives: conjunction/disjunction/negation over
          (T,F) support/refutation bits exactly as proof_records.truth_bits).
          The obligation FIRES (error contribution) iff antecedent AND target.
      FORBID @ COMPLETED — same shape, but the target atom is the
          completion of the action for those attempts; no target attempts =>
          vacuously satisfied; attempts present but completion UNKNOWN =>
          safety UNKNOWN.
      REQUIRE @ ATTEMPT  — ONE existential obligation over the WHOLE trace:
          atom attempted(action, entity, actor, THROUGH last index),
          must_be_true.  Absence of evidence: UNKNOWN; with
          history_complete + closed universe: FALSE (violation).
      REQUIRE @ COMPLETED — same with completed(...); completed has no
          absence proof path, so it stays UNKNOWN when no completion exists.
    The ANTECEDENT is the conditions tree AND NOT-exceptions, evaluated at
    the obligation's evaluation index (for FORBID: the target attempt's own
    event index, so 'before' means strictly earlier; for REQUIRE: the last
    event index).

S5. Temporal relations on the target:
      BEFORE/UNTIL anchor A — the antecedent additionally requires
          NOT attempted(A, ..., <= target index): the target may only occur
          once A has happened (violation if the target fires before A).
          (UNTIL and BEFORE lower to the same gate here; they differ in the
          RuleIR frontend, which is out of scope for the core experiment.)
      AFTER  anchor A — the antecedent requires attempted(A, ...,
          <= target index) — the target must come after A.

S6. Worlds = interpretations.  The input's interpretations form ONE material
    axis; every interpretation is one world (exact Cartesian semantics of the
    incumbent when only that axis is material).  A world's error value:
      error(world) = NOT AND(all obligation safety values, all unresolved
      markers as UNKNOWN conjuncts)
    An UNKNOWN conjunct blocks PROVED_NO_ERROR but never manufactures ERROR;
    a FALSE safety conjunct makes the world ERROR even under unrelated
    uncertainty (an independent proved violation is never masked).

S7. Final aggregate (consensus, vnext.types):
      any world error BOTH                      -> INCONSISTENT
      else any UNKNOWN / empty world space     -> UNRESOLVED
      else all TRUE                            -> PROVED_ERROR
      else all FALSE                           -> PROVED_NO_ERROR
      else                                     -> UNRESOLVED
    'ERROR in all admissible interpretations' is exactly the CAUTIOUS
    consequence of a violation; 'ERROR in some' is the BRAVE one.  The
    Clingo backend tests this equivalence explicitly instead of assuming it.

S8. Interpretation-level unresolved markers (NeutralInterpretation.unresolved)
    become UNKNOWN conjuncts of that world (S6), mirroring
    UnresolvedMarker in ReadingOption.

The engine experiment therefore starts AFTER semantic interpretation; the
scenario oracle (scenarios.py) encodes expected primitive results, expected
per-interpretation results and the expected final status derived from THIS
contract, so a backend that reaches the right final verdict for a wrong
primitive reason is still caught.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any

# --------------------------------------------------------------- vocabulary

FACT_KINDS = ("ACTION_ATTEMPTED", "ACTION_COMPLETED", "ACTION_FAILED",
              "STATE_OBSERVATION", "FIELD_VALUE", "ENTITY", "RELATION",
              "EFFECT", "CLAIM")
EVIDENCE_STATUSES = ("SUPPORTED", "REFUTED", "UNKNOWN")
REGIONS = ("history", "target")
MODALITIES = ("FORBID", "REQUIRE")
TARGET_LEVELS = ("ATTEMPT", "COMPLETED")
TEMPORAL_RELATIONS = ("NONE", "BEFORE", "UNTIL", "AFTER")
COMPARISON_OPS = ("EQ", "NE", "LT", "LE", "GT", "GE")
CARDINALITY_OPS = ("AT_LEAST", "AT_MOST", "EXACTLY")
QUERY_KINDS = ("attempted", "completed", "state", "state_hist",
               "comparison", "cardinality")
FINAL_STATUSES = ("PROVED_ERROR", "PROVED_NO_ERROR", "UNRESOLVED", "INCONSISTENT")
WORLD_VERDICTS = ("ERROR", "NO_ERROR", "UNKNOWN", "BOTH")

NEUTRAL_INPUT_SCHEMA_VERSION = "neutral-core-input/1.0"


def _check(value: Any, allowed: tuple[str, ...], what: str) -> None:
    if value not in allowed:
        raise ValueError(f"{what} must be one of {allowed}, got {value!r}")


# ------------------------------------------------------------------- facts

@dataclass(frozen=True)
class NeutralFact:
    """One classified evidence record.  The Guardian evidence layer (not any
    logic engine) decided that this fact exists with this status; engines
    consume the classification and must never re-derive it."""
    fact_id: str
    kind: str                     # FACT_KINDS
    actor: str                    # assistant | user | system | unknown
    entity: str                   # entity value ("acc-1", "order-7", "*"=any)
    predicate: str                # action name (action facts) or state predicate
    value: Any = None             # JSON value for state/field/effect/claim facts
    event_index: int = -1         # trace position (relative event order)
    call_id: str | None = None
    region: str = "history"       # REGIONS: 'target' = the response under audit
    evidence_status: str = "SUPPORTED"   # EVIDENCE_STATUSES
    source_ref: str = ""          # id into NeutralCoreInput.source_refs

    def __post_init__(self) -> None:
        _check(self.kind, FACT_KINDS, "fact kind")
        _check(self.evidence_status, EVIDENCE_STATUSES, "evidence status")
        _check(self.region, REGIONS, "region")
        if not self.fact_id or not self.predicate:
            raise ValueError("fact requires fact_id and predicate")
        if type(self.event_index) is not int or self.event_index < 0:
            raise ValueError("fact requires a non-negative event_index")
        if self.kind in ("ACTION_ATTEMPTED", "ACTION_COMPLETED", "ACTION_FAILED") \
                and self.actor in ("", "unknown"):
            raise ValueError("action facts require a known actor")


# ------------------------------------------------------------- query atoms

@dataclass(frozen=True)
class NeutralComparison:
    predicate: str                # state predicate the LHS refers to
    op: str                       # COMPARISON_OPS
    rhs_literal: Any              # JSON literal (number / string / bool)


@dataclass(frozen=True)
class NeutralCardinality:
    subject: str                  # action or state predicate being counted
    op: str                       # CARDINALITY_OPS
    count: int


@dataclass(frozen=True)
class NeutralAtom:
    """A query atom (S2).  Exactly one query kind is active; the remaining
    fields are ignored per kind.  `time_index` is the evaluation boundary."""
    atom_id: str
    kind: str                     # QUERY_KINDS
    action: str = ""              # attempted/completed/cardinality subject
    entity: str = "*"
    actor: str = "assistant"
    predicate: str = ""           # state/comparison predicate
    expected: Any = None          # expected value for state queries
    comparison: NeutralComparison | None = None
    cardinality: NeutralCardinality | None = None
    time_index: int = 10**9       # default: through the end of the trace
    region: str = "target"        # attempted/completed queries scope: which
    # region facts may SUPPORT the atom (FORBID target-level convention);
    # the incumbent evaluates FORBID on the response under audit only.

    def __post_init__(self) -> None:
        _check(self.kind, QUERY_KINDS, "query kind")
        if not self.atom_id:
            raise ValueError("atom requires atom_id")
        if self.kind in ("attempted", "completed") and not self.action:
            raise ValueError("action query requires action name")
        if self.kind in ("state", "state_hist") and not self.predicate:
            raise ValueError("state query requires predicate")
        if self.kind == "comparison":
            if self.comparison is None:
                raise ValueError("comparison query requires comparison spec")
            _check(self.comparison.op, COMPARISON_OPS, "comparison op")
        if self.kind == "cardinality":
            if self.cardinality is None:
                raise ValueError("cardinality query requires cardinality spec")
            _check(self.cardinality.op, CARDINALITY_OPS, "cardinality op")

    def key(self) -> str:
        """Canonical stable key used by every backend's primitive report."""
        if self.kind in ("attempted", "completed"):
            return (f"{self.kind}:{self.action}:{self.entity}:{self.actor}"
                    f":t{self.time_index}")
        if self.kind == "state":
            return f"state:{self.entity}:{self.predicate}={_canon(self.expected)}:t{self.time_index}"
        if self.kind == "state_hist":
            return f"state_hist:{self.entity}:{self.predicate}={_canon(self.expected)}:t{self.time_index}"
        if self.kind == "comparison":
            c = self.comparison
            return f"cmp:{self.entity}:{c.predicate}{c.op}{_canon(c.rhs_literal)}:t{self.time_index}"
        c = self.cardinality
        return f"card:{self.cardinality.subject if not self.action else self.action}:{self.entity}:{c.op}{c.count}:t{self.time_index}"


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------- condition trees

@dataclass(frozen=True)
class CondNode:
    """Boolean expression tree over atoms: {all,any,not,atom} — mirrors the
    RuleIR condition node shape one-to-one so real-replay lowering stays a
    representation map."""
    atom: NeutralAtom | None = None
    all_: tuple["CondNode", ...] | None = None
    any_: tuple["CondNode", ...] | None = None
    not_: "CondNode | None" = None

    def __post_init__(self) -> None:
        shapes = sum(x is not None for x in (self.atom, self.all_, self.any_, self.not_))
        if shapes != 1:
            raise ValueError("exactly one CondNode shape required")
        if self.all_ is not None and not self.all_:
            raise ValueError("empty all() node")
        if self.any_ is not None and not self.any_:
            raise ValueError("empty any() node")

    def leaves(self) -> list[NeutralAtom]:
        if self.atom is not None:
            return [self.atom]
        out: list[NeutralAtom] = []
        if self.all_:
            for child in self.all_:
                out.extend(child.leaves())
        if self.any_:
            for child in self.any_:
                out.extend(child.leaves())
        if self.not_ is not None:
            out.extend(self.not_.leaves())
        return out


# ------------------------------------------------------------------- rules

@dataclass(frozen=True)
class NeutralRule:
    """One already-formalized rule (S4/S5).  modality+level+action+entity is
    the obligation head; conditions/exceptions/temporal form the antecedent."""
    rule_id: str
    modality: str                 # MODALITIES
    action: str
    entity: str = "*"
    actor: str = "assistant"
    target_level: str = "ATTEMPT"  # TARGET_LEVELS
    conditions: CondNode | None = None
    exceptions: tuple[CondNode, ...] = ()
    temporal: str = "NONE"        # TEMPORAL_RELATIONS
    temporal_anchor_action: str = ""
    temporal_anchor_entity: str = "*"

    def __post_init__(self) -> None:
        _check(self.modality, MODALITIES, "modality")
        _check(self.target_level, TARGET_LEVELS, "target level")
        _check(self.temporal, TEMPORAL_RELATIONS, "temporal relation")
        if self.temporal != "NONE" and not self.temporal_anchor_action:
            raise ValueError("temporal rule requires anchor action")
        if not self.rule_id or not self.action:
            raise ValueError("rule requires rule_id and action")


@dataclass(frozen=True)
class NeutralInterpretation:
    """One admissible whole-case reading = one world (S6)."""
    interp_id: str
    rules: tuple[NeutralRule, ...] = ()
    unresolved: tuple[str, ...] = ()   # markers -> UNKNOWN conjuncts (S8)

    def __post_init__(self) -> None:
        if not self.interp_id:
            raise ValueError("interpretation requires interp_id")


# ------------------------------------------------------------- core input

@dataclass(frozen=True)
class NeutralCoreInput:
    case_id: str
    facts: tuple[NeutralFact, ...]
    interpretations: tuple[NeutralInterpretation, ...]
    history_complete: bool = False
    completeness_basis: str | None = None
    closed_action_universe: tuple[str, ...] = ()   # actions whose ABSENCE is provable
    source_refs: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("core input requires case_id")
        if self.history_complete and not self.completeness_basis:
            raise ValueError("history_complete requires explicit completeness basis")
        if not self.interpretations:
            # empty interpretation space is legal and must resolve UNRESOLVED
            pass

    # ------------------------------------------------------- serialization
    def to_json(self) -> str:
        return json.dumps(_to_plain(self), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def from_json(text: str) -> "NeutralCoreInput":
        return _from_plain(json.loads(text))

    def content_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


def _to_plain(obj: Any) -> Any:
    if isinstance(obj, NeutralCoreInput):
        return {
            "schema": NEUTRAL_INPUT_SCHEMA_VERSION,
            "case_id": obj.case_id,
            "facts": [_to_plain(f) for f in obj.facts],
            "interpretations": [_to_plain(i) for i in obj.interpretations],
            "history_complete": obj.history_complete,
            "completeness_basis": obj.completeness_basis,
            "closed_action_universe": list(obj.closed_action_universe),
            "source_refs": obj.source_refs,
            "notes": obj.notes,
        }
    if isinstance(obj, NeutralFact):
        return {"fact_id": obj.fact_id, "kind": obj.kind, "actor": obj.actor,
                "entity": obj.entity, "predicate": obj.predicate,
                "value": obj.value, "event_index": obj.event_index,
                "call_id": obj.call_id, "region": obj.region,
                "evidence_status": obj.evidence_status,
                "source_ref": obj.source_ref}
    if isinstance(obj, NeutralInterpretation):
        return {"interp_id": obj.interp_id,
                "rules": [_to_plain(r) for r in obj.rules],
                "unresolved": list(obj.unresolved)}
    if isinstance(obj, NeutralRule):
        return {"rule_id": obj.rule_id, "modality": obj.modality,
                "action": obj.action, "entity": obj.entity, "actor": obj.actor,
                "target_level": obj.target_level,
                "conditions": _to_plain(obj.conditions) if obj.conditions else None,
                "exceptions": [_to_plain(e) for e in obj.exceptions],
                "temporal": obj.temporal,
                "temporal_anchor_action": obj.temporal_anchor_action,
                "temporal_anchor_entity": obj.temporal_anchor_entity}
    if isinstance(obj, CondNode):
        return {"atom": _to_plain(obj.atom) if obj.atom else None,
                "all": [_to_plain(c) for c in obj.all_] if obj.all_ else None,
                "any": [_to_plain(c) for c in obj.any_] if obj.any_ else None,
                "not": _to_plain(obj.not_) if obj.not_ else None}
    if isinstance(obj, NeutralAtom):
        return {"atom_id": obj.atom_id, "kind": obj.kind, "action": obj.action,
                "entity": obj.entity, "actor": obj.actor,
                "predicate": obj.predicate, "expected": obj.expected,
                "comparison": _to_plain(obj.comparison) if obj.comparison else None,
                "cardinality": _to_plain(obj.cardinality) if obj.cardinality else None,
                "time_index": obj.time_index, "region": obj.region}
    if isinstance(obj, (NeutralComparison, NeutralCardinality)):
        return asdict(obj)
    raise TypeError(f"unserializable object {type(obj)!r}")


def _from_plain(data: dict) -> Any:
    if "schema" in data:
        return NeutralCoreInput(
            case_id=data["case_id"],
            facts=tuple(_from_plain(f) for f in data["facts"]),
            interpretations=tuple(_from_plain(i) for i in data["interpretations"]),
            history_complete=data["history_complete"],
            completeness_basis=data["completeness_basis"],
            closed_action_universe=tuple(data["closed_action_universe"]),
            source_refs=data["source_refs"], notes=data.get("notes", ""))
    if "fact_id" in data:
        return NeutralFact(**data)
    if "interp_id" in data:
        return NeutralInterpretation(
            interp_id=data["interp_id"],
            rules=tuple(_from_plain(r) for r in data["rules"]),
            unresolved=tuple(data["unresolved"]))
    if "rule_id" in data:
        return NeutralRule(
            rule_id=data["rule_id"], modality=data["modality"],
            action=data["action"], entity=data["entity"], actor=data["actor"],
            target_level=data["target_level"],
            conditions=_from_plain(data["conditions"]) if data["conditions"] else None,
            exceptions=tuple(_from_plain(e) for e in data["exceptions"]),
            temporal=data["temporal"],
            temporal_anchor_action=data["temporal_anchor_action"],
            temporal_anchor_entity=data["temporal_anchor_entity"])
    if "atom_id" in data:
        comp = NeutralComparison(**data["comparison"]) if data.get("comparison") else None
        card = NeutralCardinality(**data["cardinality"]) if data.get("cardinality") else None
        return NeutralAtom(atom_id=data["atom_id"], kind=data["kind"],
                           action=data["action"], entity=data["entity"],
                           actor=data["actor"], predicate=data["predicate"],
                           expected=data["expected"], comparison=comp,
                           cardinality=card, time_index=data["time_index"],
                           region=data["region"])
    if any(k in data for k in ("all", "any", "not", "atom")):
        return CondNode(
            atom=_from_plain(data["atom"]) if data.get("atom") else None,
            all_=tuple(_from_plain(c) for c in data["all"]) if data.get("all") else None,
            any_=tuple(_from_plain(c) for c in data["any"]) if data.get("any") else None,
            not_=_from_plain(data["not"]) if data.get("not") else None)
    raise ValueError(f"unrecognized plain record {sorted(data)[:6]}")


# ------------------------------------------------------------ result shapes

TRUTH_ORDER = ("TRUE", "FALSE", "BOTH", "UNKNOWN")


@dataclass(frozen=True)
class PrimitiveResult:
    atom_key: str
    value: str                      # TRUTH_ORDER member
    supports: tuple[str, ...] = ()  # fact_ids
    refutes: tuple[str, ...] = ()   # fact_ids


@dataclass(frozen=True)
class WorldResult:
    interp_id: str
    error_value: str                # TRUTH_ORDER member (error proposition)
    obligation_safety: tuple[tuple[str, str], ...] = ()   # (obligation_id, truth)


@dataclass(frozen=True)
class BackendWitness:
    """Normalized per-rule witness (S21 of the bake-off directive)."""
    rule_id: str
    interpretation_id: str
    conclusion: str                 # safety truth for this obligation
    supporting_fact_ids: tuple[str, ...] = ()
    refuting_fact_ids: tuple[str, ...] = ()
    unknown_dependencies: tuple[str, ...] = ()
    engine_native_explanation: str = ""


@dataclass(frozen=True)
class BackendResult:
    backend: str
    status: str                     # FINAL_STATUSES member or "ERROR"
    worlds: tuple[WorldResult, ...] = ()
    primitives: tuple[PrimitiveResult, ...] = ()
    witnesses: tuple[BackendWitness, ...] = ()
    runtime_ms: float = 0.0
    input_content_hash: str = ""
    notes: str = ""
    detail: str = ""                # error detail when status == "ERROR"

    def primitive_map(self) -> dict[str, str]:
        return {p.atom_key: p.value for p in self.primitives}

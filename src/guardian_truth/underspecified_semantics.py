"""Minimal underspecified-semantics prototype for falsification experiments.

This module does not parse arbitrary policy language and is not on the runtime
decision path.  It preserves a finite, inspectable version space over detected
semantic constructions.  Strict results are supervaluational: a result is
proved only when every remaining interpretation gives the same verdict.
"""

from dataclasses import dataclass, replace
from itertools import product
import math
import re
from typing import Any, Callable, Iterable, Mapping, Sequence

from .types import Source


MAX_TEXT_CHARS = 12_000
MAX_OBLIGATIONS = 64
MAX_OUTER_WIDTH = 4096
STATUSES = ("FORMALIZED", "HOLE", "RESIDUAL", "UNSUPPORTED")


@dataclass(frozen=True)
class SemanticConcept:
    id: str
    kind: str
    label: str
    roles: tuple[tuple[str, str], ...]
    source: Source
    binding_options: tuple[str, ...] = ()
    binding_status: str = "UNBOUND_CONCEPT"


@dataclass(frozen=True)
class TranslationObligation:
    id: str
    kind: str
    source: Source
    arguments: tuple[str, ...]
    possible_scopes: tuple[str, ...]
    possible_bindings: tuple[str, ...]
    recognition_basis: str
    status: str
    alternatives: tuple[str, ...]


@dataclass(frozen=True)
class StructuralHole:
    id: str
    level: str
    obligation_id: str
    alternatives: tuple[str, ...]
    source: Source


@dataclass(frozen=True)
class ExclusionConstraint:
    id: str
    hole_id: str
    excluded: tuple[str, ...]
    source: Source
    contract: str
    assumptions: tuple[str, ...]
    assurance: str
    dependencies: tuple[str, ...] = ()
    active: bool = True

    def __post_init__(self):
        if (not self.id or not self.hole_id or not self.excluded or not self.contract
                or self.assurance not in {"EXACT", "VERIFIED_DERIVATION", "HEURISTIC"}):
            raise ValueError("Every exclusion requires a bounded reason")


@dataclass(frozen=True)
class SemanticAnalysis:
    text: str
    concepts: tuple[SemanticConcept, ...]
    obligations: tuple[TranslationObligation, ...]
    holes: tuple[StructuralHole, ...]
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class Interpretation:
    choices: tuple[tuple[str, str], ...]

    def get(self, hole_id: str, default=None):
        return dict(self.choices).get(hole_id, default)


@dataclass(frozen=True)
class InterpretationSpace:
    holes: tuple[StructuralHole, ...]
    constraints: tuple[ExclusionConstraint, ...] = ()
    working_preferences: tuple[tuple[str, str], ...] = ()

    def _options(self, *, include_heuristic: bool) -> tuple[tuple[str, tuple[str, ...]], ...]:
        active = [item for item in self.constraints
                  if item.active and (include_heuristic or item.assurance != "HEURISTIC")]
        result = []
        for hole in self.holes:
            excluded = {choice for rule in active if rule.hole_id == hole.id
                        for choice in rule.excluded}
            result.append((hole.id, tuple(x for x in hole.alternatives if x not in excluded)))
        return tuple(result)

    def options(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Hard outer options; ranking heuristics are deliberately ignored."""
        return self._options(include_heuristic=False)

    def working_options(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Smaller search view; heuristic exclusions are allowed only here."""
        return self._options(include_heuristic=True)

    def width(self) -> int:
        return math.prod(len(values) for _, values in self.options())

    @staticmethod
    def _enumerate(options, limit):
        width = math.prod(len(values) for _, values in options)
        if width == 0:
            return ()
        if width > limit:
            raise ValueError("outer_width_exceeded")
        return tuple(Interpretation(tuple(zip((name for name, _ in options), values)))
                     for values in product(*(values for _, values in options)))

    def interpretations(self, *, limit=MAX_OUTER_WIDTH) -> tuple[Interpretation, ...]:
        return self._enumerate(self.options(), limit)

    def working(self, *, limit=32) -> tuple[Interpretation, ...]:
        preferred = dict(self.working_preferences)
        values = list(self._enumerate(self.working_options(), MAX_OUTER_WIDTH))
        values.sort(key=lambda item: sum(dict(item.choices).get(key) != value
                                             for key, value in preferred.items()))
        return tuple(values[:limit])

    def revise(self, constraint_id: str) -> "InterpretationSpace":
        if constraint_id not in {item.id for item in self.constraints}:
            raise ValueError("Unknown constraint")
        invalidated = {constraint_id}
        changed = True
        while changed:
            changed = False
            for item in self.constraints:
                if item.id not in invalidated and any(dep in invalidated
                                                      for dep in item.dependencies):
                    invalidated.add(item.id)
                    changed = True
        return replace(self, constraints=tuple(replace(item, active=False)
                                               if item.id in invalidated else item
                                               for item in self.constraints))


@dataclass(frozen=True)
class InvariantVerdict:
    status: str
    q1: str
    q0: str
    outer_width: int
    violation_witness: Interpretation | None = None
    no_violation_witness: Interpretation | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RepresentationNode:
    id: str
    kind: str
    obligation_ids: tuple[str, ...]


@dataclass(frozen=True)
class CoverageReport:
    complete: bool
    lost_obligations: tuple[str, ...]
    invented_nodes: tuple[str, ...]
    unresolved_obligations: tuple[str, ...]


@dataclass(frozen=True)
class InformationWitness:
    found: bool
    left: Mapping[str, Any] | None = None
    right: Mapping[str, Any] | None = None
    projection: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class StandardFactors:
    explicit_preference: bool | None
    agent_access: bool | None
    action_contradicts: bool | None
    feasible_alternative: bool | None
    hard_constraint: bool | None
    override_explained: bool | None


_CONSTRUCTIONS = (
    ("CONDITION_DIRECTION", r"\bif\s+and\s+only\s+if\b", ("IFF",), "SUBTREE"),
    ("CONDITION_DIRECTION", r"\bonly\s+if\b", ("ONLY_IF",), "SUBTREE"),
    ("EXCEPTION", r"\beven\s+if\b", ("NON_OVERRIDING_EXCEPTION", "ATTACHMENT_HOLE"), "SUBTREE"),
    ("EXCEPTION", r"\bunless\b", ("IF_NOT", "EXCEPTION"), "SUBTREE"),
    ("EXCEPTION", r"\bexcept(?:ion)?\b", ("EXCEPTION", "ATTACHMENT_HOLE"), "SUBTREE"),
    ("DISCOURSE_ATTACHMENT", r"\botherwise\b", ("ATTACH_PREVIOUS", "UNBOUND_CONTEXT"), "WHOLE_RULE"),
    ("CONDITION_DIRECTION", r"\bif\b", ("IF",), "SUBTREE"),
    ("CONNECTIVE", r"\band\b", ("AND",), "SUBTREE"),
    ("CONNECTIVE", r"\bor\b", ("OR",), "SUBTREE"),
    ("NEGATION", r"\b(?:not|no|never|cannot|can't|mustn't)\b", ("NEGATE_PREDICATE", "NEGATE_SCOPE"), "SUBTREE"),
    ("MODALITY", r"\bmust\b|\brequired\b", ("MUST",), "VALUE"),
    ("MODALITY", r"\bshould\b", ("SHOULD",), "VALUE"),
    ("MODALITY", r"\bmay\b|\bcan\b|\ballowed\b", ("MAY",), "VALUE"),
    ("QUANTIFIER", r"\b(?:all|every|each)\b", ("ALL",), "SUBTREE"),
    ("QUANTIFIER", r"\b(?:some)\b", ("SOME",), "SUBTREE"),
    ("QUANTIFIER", r"\b(?:any)\b", ("ANY", "ALL_IN_FREE_CHOICE_CONTEXT"), "SUBTREE"),
    ("COMPARISON", r"\bat\s+most\b", ("LE",), "VALUE"),
    ("COMPARISON", r"\bless\s+than\b", ("LT",), "VALUE"),
    ("COMPARISON", r"\bat\s+least\b", ("GE",), "VALUE"),
    ("TEMPORAL_RELATION", r"\bstrictly\s+after\b", ("GT",), "VALUE"),
    ("TEMPORAL_RELATION", r"\bat\s+or\s+after\b", ("GE",), "VALUE"),
    ("TEMPORAL_RELATION", r"\bbefore\b", ("BEFORE",), "BINDING"),
    ("TEMPORAL_RELATION", r"\bafter\b", ("AFTER",), "BINDING"),
    ("STATE_VERSION", r"\b(?:current|currently|latest|now|previous|earlier|stale)\b", ("LATEST", "HISTORICAL"), "BINDING"),
    ("REFERENCE", r"\b(?:it|its|they|their|this|that)\b", ("COREFERENCE", "UNBOUND_REFERENCE"), "BINDING"),
    ("STRUCTURED_STANDARD", r"\b(?:preference|preferences|interests?|reasonable|reasonably)\b", ("FACTORIZE",), "WHOLE_RULE"),
)

_CONCEPTS = (
    ("EVENT", r"\b(?:arrive|arrives|arrived|arrival)\b", "ArrivalEvent", (("role", "Arrival"),)),
    ("EVENT", r"\b(?:depart|departs|departed|departure)\b", "DepartureEvent", (("role", "Departure"),)),
    ("EVENT_TIME", r"\barrival\s+(?:date|time)\b", "ArrivalEventTime", (("role", "Arrival"), ("subject", "Flight"))),
    ("EVENT_TIME", r"\bdeparture\s+(?:date|time)\b", "DepartureEventTime", (("role", "Departure"), ("subject", "Flight"))),
)


def _source(start, end):
    return Source("rule", start, end)


def _overlaps(span, occupied):
    return any(span[0] < right and span[1] > left for left, right in occupied)


def _schema_bind(kind: str, label: str, fields: Sequence[str],
                 entity_hint: tuple[str, str] | None = None) -> tuple[tuple[str, ...], str]:
    normalized = {field: set(re.findall(r"[a-z0-9]+", field.replace("_", " ").lower()))
                  for field in fields}
    if kind in {"EVENT", "EVENT_TIME"}:
        role = "arrival" if label.startswith("Arrival") else "departure"
        candidates = []
        for field, words in normalized.items():
            if role not in words or (kind != "EVENT" and not words & {"date", "time", "datetime"}):
                continue
            if entity_hint and entity_hint[0] in words:
                other_ids = words - {entity_hint[0], role, "date", "time", "datetime"}
                if other_ids and entity_hint[1] not in other_ids:
                    continue
            candidates.append(field)
        candidates = tuple(candidates)
    else:
        words = set(re.findall(r"[a-z0-9]+", label.lower()))
        candidates = tuple(field for field, value in normalized.items() if words <= value)
    if len(candidates) == 1:
        return candidates, "BOUND_VERIFIED"
    if candidates:
        return candidates, "BINDING_HOLE"
    return (), "UNBOUND_CONCEPT"


def analyze_rule(text: str, *, schema_fields: Iterable[str] = ()) -> SemanticAnalysis:
    """Detect a bounded registry of semantic constructions without choosing an AST."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
        raise ValueError("Invalid rule text")
    fields = tuple(dict.fromkeys(field for field in schema_fields
                                 if isinstance(field, str) and field.strip()))
    concepts = []
    named_entities = tuple(dict.fromkeys(
        (kind.lower(), name.lower())
        for kind, name in re.findall(r"\b(Flight|Account|Booking)\s+([A-Za-z0-9]+)\b", text, re.I)))
    entity_hint = named_entities[0] if len(named_entities) == 1 else None
    for kind, pattern, label, roles in _CONCEPTS:
        for match in re.finditer(pattern, text, re.I):
            options, status = _schema_bind(kind, label, fields, entity_hint)
            concepts.append(SemanticConcept(f"c{len(concepts)}", kind, label, roles,
                                            _source(*match.span()), options, status))
    # Generic field concepts are semantic mentions first, never forced schema bindings.
    occupied = [(item.source.start, item.source.end) for item in concepts]
    for match in re.finditer(r"\b(?:[A-Za-z][A-Za-z'-]*\s+){0,3}(?:status|state|date|time|amount|price|level)\b", text, re.I):
        if _overlaps(match.span(), occupied):
            continue
        label = match[0].strip()
        words = set(re.findall(r"[a-z0-9]+", label.lower()))
        candidates = tuple(field for field in fields
                           if words <= set(re.findall(r"[a-z0-9]+", field.replace("_", " ").lower())))
        status = "BOUND_VERIFIED" if len(candidates) == 1 else "BINDING_HOLE" if candidates else "UNBOUND_CONCEPT"
        concepts.append(SemanticConcept(f"c{len(concepts)}", "FIELD_CONCEPT", label, (),
                                        _source(*match.span()), candidates, status))

    obligations = []
    protected_cues = []
    # Only longer alternatives in the same cue family own their inner generic
    # token (ONLY_IF owns IF; STRICTLY_AFTER owns AFTER). Cross-family overlap,
    # such as negation inside an exception, must remain visible.
    for kind, pattern, alternatives, level in _CONSTRUCTIONS:
        for match in re.finditer(pattern, text, re.I):
            generic_if = kind == "CONDITION_DIRECTION" and alternatives == ("IF",)
            generic_after = kind == "TEMPORAL_RELATION" and alternatives == ("AFTER",)
            if ((generic_if or generic_after)
                    and any(match.start() >= left and match.end() <= right
                            for left, right in protected_cues)):
                continue
            if (kind in {"CONDITION_DIRECTION", "EXCEPTION"} and "if" in match[0].lower()
                    and alternatives != ("IF",)) or (
                    kind == "TEMPORAL_RELATION" and alternatives in {("GT",), ("GE",)}):
                protected_cues.append(match.span())
            status = ("RESIDUAL" if kind == "STRUCTURED_STANDARD" else
                      "UNSUPPORTED" if kind == "DISCOURSE_ATTACHMENT" and "UNBOUND_CONTEXT" in alternatives else
                      "HOLE" if len(alternatives) > 1 else "FORMALIZED")
            scopes = ("LOCAL_CLAUSE", "WHOLE_RULE") if level in {"SUBTREE", "WHOLE_RULE"} else ("LOCAL",)
            obligations.append(TranslationObligation(
                f"o{len(obligations)}", kind, _source(*match.span()), (match[0],), scopes,
                (), f"lexical:{pattern}", status, alternatives))
    # Every semantic concept creates an explicit binding obligation.
    for concept in concepts:
        alternatives = concept.binding_options or (concept.binding_status,)
        status = "FORMALIZED" if concept.binding_status == "BOUND_VERIFIED" else "HOLE"
        if concept.binding_status == "UNBOUND_CONCEPT":
            status = "UNSUPPORTED"
        obligations.append(TranslationObligation(
            f"o{len(obligations)}", "CONCEPT_BINDING", concept.source, (concept.id,),
            ("CONCEPT",), alternatives, "semantic_concept_then_schema", status, alternatives))
    # Mixed modalities or multiple sentences are an explicit whole-rule question.
    modalities = {item.alternatives[0] for item in obligations if item.kind == "MODALITY"}
    sentences = [x for x in re.split(r"(?<=[.!?])\s+", text.strip()) if x]
    if len(modalities) > 1 or len(sentences) > 1:
        alternatives = ("COMPOUND_RULE", "SEPARATE_RULES", "WHOLE_RULE_RESIDUAL")
        obligations.append(TranslationObligation(
            f"o{len(obligations)}", "RULE_STRUCTURE", _source(0, len(text)), (),
            ("WHOLE_RULE",), (), "sentence_and_modality_structure", "HOLE", alternatives))
    # Until an independent equivalence validator proves the detected fragments
    # exhaustive, preserve a whole-rule escape hatch.  It may be irrelevant to a
    # hard violation, but it may never silently disappear.
    obligations.append(TranslationObligation(
        f"o{len(obligations)}", "SEMANTIC_RESIDUAL", _source(0, len(text)), (),
        ("WHOLE_RULE",), (), "no_complete_semantic_equivalence_certificate",
        "RESIDUAL", ("RESIDUAL_FALSE", "RESIDUAL_TRUE")))
    if len(obligations) > MAX_OBLIGATIONS:
        return SemanticAnalysis(text, tuple(concepts), tuple(obligations[:MAX_OBLIGATIONS]), (),
                                ("obligation_limit",))
    holes = []
    for obligation in obligations:
        if obligation.status in {"HOLE", "RESIDUAL", "UNSUPPORTED"}:
            level = next((item[3] for item in _CONSTRUCTIONS if item[0] == obligation.kind),
                         "BINDING" if obligation.kind == "CONCEPT_BINDING" else "WHOLE_RULE")
            alternatives = obligation.alternatives
            if obligation.status == "RESIDUAL":
                alternatives = ("RESIDUAL_FALSE", "RESIDUAL_TRUE")
            elif obligation.status == "UNSUPPORTED" and len(alternatives) == 1:
                alternatives = (alternatives[0], "MISSING_CONCEPT")
            holes.append(StructuralHole(f"h{len(holes)}", level, obligation.id,
                                        alternatives, obligation.source))
    issues = tuple(sorted({concept.binding_status for concept in concepts
                           if concept.binding_status != "BOUND_VERIFIED"}))
    return SemanticAnalysis(text, tuple(concepts), tuple(obligations), tuple(holes), issues)


def build_outer_space(analysis: SemanticAnalysis,
                      constraints: Iterable[ExclusionConstraint] = (),
                      working_preferences: Mapping[str, str] | None = None) -> InterpretationSpace:
    if not isinstance(analysis, SemanticAnalysis):
        raise TypeError("analysis required")
    rules = tuple(constraints)
    holes = {hole.id: hole for hole in analysis.holes}
    if any(rule.hole_id not in holes or any(choice not in holes[rule.hole_id].alternatives
                                            for choice in rule.excluded) for rule in rules):
        raise ValueError("Constraint outside outer space")
    preferences = tuple(sorted((working_preferences or {}).items()))
    if any(key not in holes or value not in holes[key].alternatives for key, value in preferences):
        raise ValueError("Invalid working preference")
    return InterpretationSpace(analysis.holes, rules, preferences)


def solve_invariant(space: InterpretationSpace,
                    violation: Callable[[Interpretation], bool | None],
                    *, limit=MAX_OUTER_WIDTH) -> InvariantVerdict:
    """Evaluate Q1=K∧V and Q0=K∧¬V over a finite outer space."""
    try:
        interpretations = space.interpretations(limit=limit)
    except ValueError:
        return InvariantVerdict("COMPUTATION_UNRESOLVED", "UNKNOWN", "UNKNOWN",
                                space.width(), reason="outer_width_exceeded")
    if not interpretations:
        return InvariantVerdict("EMPTY_SPACE", "UNSAT", "UNSAT", 0)
    yes = no = unknown = None
    invalid = False
    for item in interpretations:
        result = violation(item)
        if result is not None and type(result) is not bool:
            invalid = True
        elif result is True:
            if yes is None:
                yes = item
        elif result is False:
            if no is None:
                no = item
        elif result is None:
            unknown = item
    if unknown is not None or invalid:
        return InvariantVerdict("COMPUTATION_UNRESOLVED", "UNKNOWN", "UNKNOWN",
                                len(interpretations), yes, no,
                                ("invalid_evaluator_result" if invalid
                                 else "evaluator_returned_unknown"))
    q1, q0 = ("SAT" if yes else "UNSAT"), ("SAT" if no else "UNSAT")
    status = ("PROVED_VIOLATION" if yes and not no else
              "PROVED_NO_VIOLATION" if no and not yes else "UNRESOLVED")
    return InvariantVerdict(status, q1, q0, len(interpretations), yes, no)


def solve_guarded(analysis: SemanticAnalysis,
                  nodes: Sequence[RepresentationNode],
                  accounted_obligations: Iterable[str],
                  space: InterpretationSpace,
                  violation: Callable[[Interpretation], bool | None],
                  *, limit=MAX_OUTER_WIDTH) -> InvariantVerdict:
    """Permit a strict proof only after bidirectional discovered-coverage passes."""
    if "obligation_limit" in analysis.issues:
        return InvariantVerdict("UNRESOLVED", "UNKNOWN", "UNKNOWN", space.width(),
                                reason="analysis_incomplete")
    if space.holes != analysis.holes:
        return InvariantVerdict("UNRESOLVED", "UNKNOWN", "UNKNOWN", space.width(),
                                reason="space_mismatch")
    coverage = check_bidirectional_coverage(analysis, nodes, accounted_obligations)
    if not coverage.complete:
        return InvariantVerdict("UNRESOLVED", "UNKNOWN", "UNKNOWN", space.width(),
                                reason="coverage_incomplete")
    return solve_invariant(space, violation, limit=limit)


def check_bidirectional_coverage(analysis: SemanticAnalysis,
                                 nodes: Sequence[RepresentationNode],
                                 accounted_obligations: Iterable[str]) -> CoverageReport:
    obligation_ids = {item.id for item in analysis.obligations}
    accounted = set(accounted_obligations)
    node_refs = {ref for node in nodes for ref in node.obligation_ids}
    formalized_without_node = {item.id for item in analysis.obligations
                               if item.status == "FORMALIZED" and item.id not in node_refs}
    lost = tuple(sorted((obligation_ids - accounted) | formalized_without_node))
    invented = tuple(sorted(node.id for node in nodes
                             if not node.obligation_ids
                             or any(item not in obligation_ids for item in node.obligation_ids)))
    unresolved = tuple(sorted(item.id for item in analysis.obligations
                              if item.status != "FORMALIZED" and item.id not in accounted))
    return CoverageReport(not lost and not invented, lost, invented, unresolved)


def information_insufficiency_witness(worlds: Sequence[Mapping[str, Any]],
                                       projection_keys: Sequence[str],
                                       violation_key: str) -> InformationWitness:
    """Find equal observable projections with opposite violation values."""
    seen = {}
    for world in worlds:
        if violation_key not in world or type(world[violation_key]) is not bool:
            continue
        projection = tuple((key, world.get(key)) for key in projection_keys)
        prior = seen.get(projection)
        if prior is not None and prior[violation_key] != world[violation_key]:
            return InformationWitness(True, prior, world, dict(projection))
        seen[projection] = world
    return InformationWitness(False)


def classify_standard(text: str) -> str:
    if re.search(r"\b(?:reasonable|reasonably|fair|interests?)\b", text, re.I):
        return "OPEN_TEXTURED"
    if re.search(r"\b(?:preference|preferences|best interest)\b", text, re.I):
        return "STRUCTURED_STANDARD"
    return "HARD_OPERATIONAL"


def evaluate_structured_standard(factors: StandardFactors) -> str:
    values = (factors.explicit_preference, factors.agent_access,
              factors.action_contradicts, factors.feasible_alternative)
    if any(value is False for value in values) or factors.hard_constraint is True or factors.override_explained is True:
        return "NO_EXPLICIT_VIOLATION_FOUND"
    if all(value is True for value in values) and factors.hard_constraint is False and factors.override_explained is False:
        return "PROVED_VIOLATION"
    return "UNRESOLVED"


def residual_invariant(evaluator: Callable[[bool], bool | None]) -> InvariantVerdict:
    hole = StructuralHole("residual", "WHOLE_RULE", "residual_obligation",
                          ("FALSE", "TRUE"), _source(0, 1))
    space = InterpretationSpace((hole,))
    return solve_invariant(space, lambda item: evaluator(item.get("residual") == "TRUE"))


def counterfactual_factor_sensitivity(factors: StandardFactors, field_name: str) -> bool:
    if field_name not in StandardFactors.__dataclass_fields__:
        raise ValueError("Unknown factor")
    current = getattr(factors, field_name)
    if type(current) is not bool:
        return False
    return evaluate_structured_standard(factors) != evaluate_structured_standard(
        replace(factors, **{field_name: not current}))

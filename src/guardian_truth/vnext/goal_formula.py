"""Goal v2 formula lowering. Meanings and bindings never establish primitive facts.

This is a development component, not a new certificate or Core verdict format.
Bindings must be grounded and independently checked before production integration.
"""

from dataclasses import dataclass
from enum import Enum

from .goal_native import GoalClause, GoalOperator
from .goal_call_membership_v2 import GoalCallMembershipAtom
from .goal_progress_v2 import PlanProgressAtom, PlanProgressKind
from .proof_records import AtomKind, ProofAtom, TimeMode, conjunction, disjunction, negate
from .types import CoverageStatus, Truth


class FormulaOperator(str, Enum):
    ATOM = "ATOM"
    NOT = "NOT"
    AND = "AND"
    OR = "OR"
    IMPLIES = "IMPLIES"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class GoalFormula:
    operator: FormulaOperator
    children: tuple["GoalFormula", ...] = ()
    atom: ProofAtom | PlanProgressAtom | GoalCallMembershipAtom | None = None

    def __post_init__(self):
        if not isinstance(self.operator, FormulaOperator):
            raise ValueError("typed formula operator required")
        arities = {FormulaOperator.ATOM: 0, FormulaOperator.UNKNOWN: 0,
                   FormulaOperator.NOT: 1, FormulaOperator.IMPLIES: 2}
        if self.operator in arities and len(self.children) != arities[self.operator]:
            raise ValueError("invalid formula arity")
        if (self.operator is FormulaOperator.ATOM) != isinstance(self.atom, (ProofAtom, PlanProgressAtom, GoalCallMembershipAtom)):
            raise ValueError("only leaf formulas carry typed proof atoms")
        if any(not isinstance(child, GoalFormula) for child in self.children):
            raise ValueError("typed formula children required")


@dataclass(frozen=True)
class CompiledGoalClause:
    clause: GoalClause
    formula: GoalFormula
    unresolved_terms: tuple[str, ...] = ()
    # The compiler cannot manufacture a closed meaning universe.
    coverage_upper_bound: CoverageStatus = CoverageStatus.EMPIRICALLY_COVERED


def compile_goal_clause(clause, bindings):
    """Bindings: (source_id, semantic_role) -> one primitive per possible world.

    No confidence-based selection: callers must enumerate alternative worlds.
    An active-step predicate requires progress evidence, not an LLM step index.
    Scope applicability must be proved separately from argument compliance.
    """
    missing = list(clause.unresolved_terms)
    unknown = GoalFormula(FormulaOperator.UNKNOWN)

    def leaf(source, role):
        atom = bindings.get((source, role))
        if not isinstance(atom, (ProofAtom, PlanProgressAtom, GoalCallMembershipAtom)):
            missing.append(f"unbound:{source}:{role}")
            return unknown
        return GoalFormula(FormulaOperator.ATOM, atom=atom)

    def implication(left, right):
        return GoalFormula(FormulaOperator.IMPLIES, (left, right))

    def inverse(value):
        return GoalFormula(FormulaOperator.NOT, (value,))

    op, operands = clause.operator, clause.operands
    arities = {GoalOperator.PLAN_STEP: 1, GoalOperator.SCOPE: 1,
        GoalOperator.BEFORE: 2, GoalOperator.REQUIRES: 1, GoalOperator.FORBIDS: 1,
        GoalOperator.IF: 2, GoalOperator.ONLY_IF: 2, GoalOperator.UNLESS: 2,
        GoalOperator.NO_EXTRA_CONSTRAINT: 0}
    if op not in arities or len(operands) != arities[op] or not clause.source_ids:
        missing.append("unsupported_or_ungrounded_clause")
        result = unknown
    elif op is GoalOperator.PLAN_STEP:
        result = implication(leaf(operands[0], "active_step"), leaf(operands[0], "step_satisfied"))
    elif op is GoalOperator.SCOPE:
        result = implication(leaf(operands[0], "scope_applicable"), leaf(operands[0], "scope_compliant"))
    elif op is GoalOperator.BEFORE:
        previous = leaf(operands[0], "prior_completion")
        current = leaf(operands[1], "current_attempt")
        # The earlier action must have completed BEFORE the later invocation.
        # A promise, attempted read, later state or same-time call is insufficient.
        prior_is_completion = (isinstance(previous.atom, ProofAtom)
            and previous.atom.kind in {AtomKind.ACTION_COMPLETED, AtomKind.HISTORICAL_ACTION}) or (
            isinstance(previous.atom, PlanProgressAtom) and previous.atom.kind is PlanProgressKind.COMPLETED_STEP)
        current_is_attempt = isinstance(current.atom, GoalCallMembershipAtom) or (
            isinstance(current.atom, ProofAtom) and current.atom.kind in {AtomKind.CALL_ATTEMPTED, AtomKind.TARGET_CALL_MATCH}
            and current.atom.time_mode is TimeMode.AT)
        if (not prior_is_completion or not current_is_attempt
                or previous.atom.actor != current.atom.actor
                or previous.atom.time_index >= current.atom.time_index):
            missing.append("unproved_order_binding")
            result = unknown
        else:
            result = implication(current, previous)
    elif op is GoalOperator.REQUIRES:
        result = leaf(operands[0], "proposition")
    elif op is GoalOperator.FORBIDS:
        result = inverse(leaf(operands[0], "proposition"))
    elif op in {GoalOperator.IF, GoalOperator.ONLY_IF}:
        # IF condition -> required action; ONLY_IF action -> necessary condition.
        # Operand roles, not the operator's name, determine these two directions.
        result = implication(leaf(operands[0], "proposition"), leaf(operands[1], "proposition"))
    elif op is GoalOperator.UNLESS:
        # Operands are exception, prohibited action; a waiver is not a mandate.
        result = implication(inverse(leaf(operands[0], "proposition")),
                             inverse(leaf(operands[1], "proposition")))
    else:
        # No extra constraint means an empty additional obligation, NOT closure.
        # Core NO_ERROR still needs a separate authoritative completeness proof.
        result = GoalFormula(FormulaOperator.AND)
    return CompiledGoalClause(clause, result, tuple(dict.fromkeys(missing)))


def evaluate_goal_formula(formula, prove):
    """Evaluate every leaf using the evidence prover; no short-cut fact creation."""
    if formula.operator is FormulaOperator.UNKNOWN:
        return Truth.UNKNOWN
    if formula.operator is FormulaOperator.ATOM:
        value = prove(formula.atom)
        if not isinstance(value, Truth):
            raise ValueError("evidence prover must return typed four-valued truth")
        return value
    values = tuple(evaluate_goal_formula(child, prove) for child in formula.children)
    if formula.operator is FormulaOperator.NOT:
        return negate(values[0])
    if formula.operator is FormulaOperator.AND:
        return conjunction(values)
    if formula.operator is FormulaOperator.OR:
        return disjunction(values)
    return disjunction((negate(values[0]), values[1]))


def evaluate_compiled_clause(compiled, prove):
    value = evaluate_goal_formula(compiled.formula, prove)
    # An unsupported material binding must not be masked by vacuous implication.
    return Truth.UNKNOWN if compiled.unresolved_terms else value

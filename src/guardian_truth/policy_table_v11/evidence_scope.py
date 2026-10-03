"""Evidence requirements have a scope; an argument proxy cannot prove dialogue state."""
from typing import Literal
from pydantic import Field
from guardian_truth.policy_table.schema import Strict
from .schema import Expression

Scope = Literal['CALL_SYNTAX', 'OBSERVATION_FACT', 'DIALOGUE_STATE', 'PRIOR_ATTEMPT', 'CONTEXT_FACT']


class ScopedObligation(Strict):
    obligation_id: str
    required_scopes: list[Scope] = Field(min_length=1)


def expression_scopes(expr):
    expr = Expression.model_validate(expr) if isinstance(expr, dict) else expr
    if expr.kind in ('ANY_OF', 'ALL_OF'):
        children=[expression_scopes(e) for e in expr.items]
        # Every alternative must preserve required evidence. One syntax-only OR
        # branch must not launder a dialogue prerequisite into argument presence.
        if expr.kind=='ANY_OF':return set.intersection(*children)
        return set.union(*children)
    if expr.kind == 'CONFIRMATION': return {'DIALOGUE_STATE'}
    if expr.kind == 'PRIOR_CALL': return {'PRIOR_ATTEMPT'}
    result = set()
    paths = [expr.lhs] + ([expr.rhs.path] if expr.rhs and expr.rhs.kind == 'PATH' else [])
    for path in paths:
        if path.startswith('args.'): result.add('CALL_SYNTAX')
        elif path.startswith('state.'): result.add('OBSERVATION_FACT')
        elif path.startswith('user.'): result.add('DIALOGUE_STATE')
        elif path.startswith('ctx.'): result.add('CONTEXT_FACT')
    return result


def validate_obligation_scope(obligation, requirement):
    expected = ScopedObligation.model_validate(obligation)
    required = set(expected.required_scopes)
    supplied = expression_scopes(requirement)
    missing = required - supplied
    return {'accepted': not missing, 'required': sorted(required), 'supplied': sorted(supplied),
            'missing': sorted(missing), 'semantic_equivalence_proven': False}

"""Evidence requirements have a scope; an argument proxy cannot prove dialogue state."""
import re
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


# Dialogue-state obligations: the requirement is about what the *user* said,
# agreed to or supplied. Such an obligation can only be discharged by evidence
# read from user-role turns (CONFIRMATION / user.* paths), never by the mere
# presence of a call argument. Lexicon is bilingual (en/ru) and domain-free.
_DIALOGUE = re.compile(r"""(?ix)
    \b(?:explicit(?:ly)?\s+(?:user\s+)?(?:confirm|consent|agree|approv)\w*
       |(?:user|customer|client)\s+(?:must\s+|should\s+|has\s+to\s+)?(?:confirm|consent|agree|approve|provide|state|say)\w*
       |obtain\w*\s+(?:the\s+)?(?:user|customer)\w*\s+(?:confirmation|consent|approval)
       |(?:confirmation|consent|approval)\s+(?:from|of)\s+(?:the\s+)?(?:user|customer|client)
       |ask\w*\s+(?:the\s+)?(?:user|customer)\s+(?:for|to)\s+(?:confirm|consent|approv|explicit)\w*
       |\(yes\)
       |явн\w*\s+(?:согласи|подтвержд)\w*
       |(?:пользовател|клиент)\w*\s+(?:должен\s+)?(?:подтверд|соглас|предостав|сообщ)\w*
       |согласи\w*\s+(?:пользовател|клиент)\w*
       |подтвержден\w*\s+(?:от\s+)?(?:пользовател|клиент)\w*)""")


def infer_required_scopes(text):
    """Conservative scope inference from source text; empty list means 'no constraint'."""
    return ['DIALOGUE_STATE'] if isinstance(text, str) and _DIALOGUE.search(text) else []


def presence_only(expr):
    """True if an expression can be satisfied by argument presence alone (schema, not policy)."""
    expr = Expression.model_validate(expr) if isinstance(expr, dict) else expr
    if expr.kind == 'ANY_OF': return any(presence_only(e) for e in expr.items)
    if expr.kind == 'ALL_OF': return all(presence_only(e) for e in expr.items)
    return (expr.kind == 'COMPARE' and expr.op in ('exists', 'not_exists') and expr.rhs is None
            and expr.lhs.startswith('args.'))

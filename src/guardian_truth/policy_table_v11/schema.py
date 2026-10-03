from typing import Literal
from pydantic import Field, model_validator
from guardian_truth.policy_table.schema import Strict, PathOperand, LiteralOperand, Trigger

Quantifier = Literal['TARGET', 'ANY', 'ALL']


class Binding(Strict):
    argument: str
    record_field: str  # '$key' is the structural key, '*' is a scalar array item.


class Expression(Strict):
    kind: Literal['COMPARE', 'ANY_OF', 'ALL_OF', 'PRIOR_CALL', 'CONFIRMATION']
    lhs: str | None = None
    op: Literal['==', '!=', '<', '<=', '>', '>=', 'in', 'not_in', 'exists', 'not_exists', 'before', 'after'] | None = None
    rhs: PathOperand | LiteralOperand | None = None
    items: list['Expression'] | None = None
    tool: str | None = None
    quantifier: Quantifier | None = None
    binding: Binding | None = None

    @model_validator(mode='after')
    def shape(self):
        if self.kind == 'COMPARE':
            if self.lhs is None or self.op is None or self.items is not None or self.tool is not None:
                raise ValueError('COMPARE requires lhs/op only')
            if (self.op in ('exists', 'not_exists')) != (self.rhs is None): raise ValueError('wrong comparison arity')
        elif self.kind in ('ANY_OF', 'ALL_OF'):
            if not self.items or any(v is not None for v in (self.lhs, self.op, self.rhs, self.tool, self.quantifier, self.binding)):
                raise ValueError('boolean expression requires nonempty items only')
        elif self.kind == 'PRIOR_CALL':
            if not self.tool or any(v is not None for v in (self.lhs, self.op, self.rhs, self.items, self.quantifier)):
                raise ValueError('PRIOR_CALL requires tool and optional entity binding')
        elif any(v is not None for v in (self.lhs, self.op, self.rhs, self.items, self.tool, self.quantifier, self.binding)):
            raise ValueError('CONFIRMATION has no parameters')
        return self


class Atom(Strict):
    modality: Literal['REQUIRES', 'FORBIDS', 'REQUIRES_PRIOR_CALL', 'REQUIRES_USER_CONFIRMATION']
    condition: Expression | None = None
    prior_call: str | None = None
    confirmation: bool | None = None
    quantifier: Quantifier | None = None
    binding: Binding | None = None
    clause_ids: list[str] = Field(min_length=1)
    exceptions: list[Expression]
    guard: Expression | None = None  # Applicability is distinct from the necessary condition.

    @model_validator(mode='after')
    def one_requirement(self):
        if self.modality in ('REQUIRES', 'FORBIDS'):
            if self.condition is None or self.prior_call is not None or self.confirmation is not None:
                raise ValueError('condition modality requires exactly condition')
            if self.quantifier is not None or self.binding is not None:
                if self.condition.kind != 'COMPARE': raise ValueError('top-level quantifier only on COMPARE')
                if self.condition.quantifier not in (None, self.quantifier) or self.condition.binding not in (None, self.binding):
                    raise ValueError('conflicting condition quantifier/binding')
                self.condition = self.condition.model_copy(update={'quantifier': self.quantifier or self.condition.quantifier,
                    'binding': self.binding or self.condition.binding})
                self.quantifier = None; self.binding = None
        elif self.modality == 'REQUIRES_PRIOR_CALL':
            if not self.prior_call or self.condition is not None or self.confirmation is not None or self.quantifier is not None:
                raise ValueError('prior modality requires prior_call and optional binding')
        else:
            if self.confirmation is not True or any(v is not None for v in (self.condition, self.prior_call, self.quantifier, self.binding)):
                raise ValueError('confirmation modality requires confirmation:true only')
        return self


def requirement(atom):
    if atom.condition is not None: return atom.condition
    if atom.prior_call: return Expression(kind='PRIOR_CALL', tool=atom.prior_call, binding=atom.binding)
    return Expression(kind='CONFIRMATION')


def wire_dump(model):
    """Drop optional null fields while preserving opaque, required literal values."""
    def clean(value):
        if isinstance(value, list): return [clean(v) for v in value]
        if not isinstance(value, dict): return value
        if value.get('kind') == 'LITERAL': return value  # value:null and nulls inside JSON literals are data.
        return {k: clean(v) for k, v in value.items() if v is not None}
    return clean(model.model_dump())

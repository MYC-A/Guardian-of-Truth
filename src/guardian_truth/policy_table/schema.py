from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class PathOperand(Strict):
    kind: Literal['PATH']
    path: str


class LiteralOperand(Strict):
    kind: Literal['LITERAL']
    value: str | int | float | bool | None | list[str | int | float | bool | None]


class Condition(Strict):
    lhs: str
    op: Literal['==', '!=', '<', '<=', '>', '>=', 'in', 'not_in', 'exists', 'not_exists', 'before', 'after']
    rhs: PathOperand | LiteralOperand | None = None

    @model_validator(mode='after')
    def arity(self):
        if (self.op in ('exists', 'not_exists')) != (self.rhs is None):
            raise ValueError('presence operator is unary, all other operators require rhs')
        return self


class Trigger(Strict):
    kind: Literal['TOOL_CALL', 'SPEECH_ACT']
    tool: str | None = None
    act: Literal['REFUSE', 'TRANSFER', 'ASK_USER', 'ASSERT_DONE', 'ASSERT_FACT'] | None = None

    @model_validator(mode='after')
    def exclusive(self):
        if self.kind == 'TOOL_CALL' and (not self.tool or self.act is not None):
            raise ValueError('tool trigger requires exactly a tool')
        if self.kind == 'SPEECH_ACT' and (self.tool is not None or self.act is None):
            raise ValueError('speech trigger requires exactly an act')
        return self


class Rule(Strict):
    rule_id: str = Field(min_length=1)
    clause_ids: list[str] = Field(min_length=1)
    trigger: Trigger
    modality: Literal['REQUIRES', 'FORBIDS', 'REQUIRES_PRIOR_CALL', 'REQUIRES_USER_CONFIRMATION']
    conditions: list[Condition]
    exceptions: list[list[Condition]]
    prior_call: str | None = None
    compile_status: Literal['COMPILED', 'PARTIAL', 'NOT_COMPILABLE']
    not_compilable_reason: str | None = None

    @model_validator(mode='after')
    def prior_and_status(self):
        if (self.modality == 'REQUIRES_PRIOR_CALL') != (self.prior_call is not None):
            raise ValueError('only prior-call modality requires prior_call')
        if self.modality == 'REQUIRES' and not self.conditions:
            raise ValueError('required conditions cannot be empty')
        if any(not group for group in self.exceptions):
            raise ValueError('exception group must not be empty')
        if self.compile_status != 'COMPILED' and not self.not_compilable_reason:
            raise ValueError('incomplete compilation requires its reason')
        return self


class Compilation(Strict):
    rules: list[Rule]
    uncovered_clause_ids: list[str]


class Table(Strict):
    schema_version: Literal['guardian-policy-table/1'] = 'guardian-policy-table/1'
    policy_sha256: str
    source_policy: str
    clauses: list[dict]
    enum_catalog: dict
    samples: list[dict]
    rules: list[dict]
    discarded: list[dict]
    coverage: dict
    compilation_metadata: dict = Field(default_factory=dict)

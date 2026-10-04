"""Small model contracts; source correctness and semantic correctness differ."""
from typing import Literal

from pydantic import Field, model_validator

from guardian_truth.policy_table.schema import Strict


class Span(Strict):
    source_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode='after')
    def ordered(self):
        if self.end <= self.start:
            raise ValueError('empty_or_reversed_span')
        return self


class Formula(Strict):
    op: Literal['ATOM', 'AND', 'OR', 'NOT', 'BEFORE', 'AFTER', 'UNKNOWN']
    label: str = Field(min_length=1)
    spans: list[Span] = Field(min_length=1)
    children: list['Formula']

    @model_validator(mode='after')
    def arity(self):
        n = len(self.children)
        if ((self.op in ('ATOM', 'UNKNOWN') and n != 0)
                or (self.op in ('AND', 'OR') and n < 2)
                or (self.op == 'NOT' and n != 1)
                or (self.op in ('BEFORE', 'AFTER') and n != 2)):
            raise ValueError('wrong_formula_arity')
        return self


class Requirement(Strict):
    local_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    action_spans: list[Span] = Field(min_length=1)
    scope: str = Field(min_length=1)
    source_spans: list[Span] = Field(min_length=1)
    modality: Literal['REQUIRE', 'FORBID', 'PERMIT']
    condition: Formula
    guard: Formula | None
    exceptions: list[Formula]
    open_questions: list[str]


class InventoryReply(Strict):
    unit_id: str
    status: Literal['REVIEWED', 'UNRESOLVED']
    reason: str = Field(min_length=1)
    requirements: list[Requirement]


class EffectReply(Strict):
    tool: str
    effect: Literal['READ', 'MODIFY', 'CREATE', 'DELETE', 'COMMUNICATE', 'OTHER', 'UNKNOWN']
    action: str = Field(min_length=1)
    spans: list[Span] = Field(min_length=1)
    object_type: str = Field(min_length=1)
    object_spans: list[Span] = Field(min_length=1)
    reason: str = Field(min_length=1)


class LinkReply(Strict):
    target_id: str
    requirement_id: str
    status: Literal['APPLIES', 'DOES_NOT_APPLY', 'UNRESOLVED']
    policy_spans: list[Span] = Field(min_length=1)
    declaration_spans: list[Span] = Field(min_length=1)
    reason: str = Field(min_length=1)


class FactOperand(Strict):
    kind: Literal['NATIVE_JSON', 'SOURCE_LITERAL']
    source_id: str
    pointer: str | None
    literal_span: Span | None

    @model_validator(mode='after')
    def shape(self):
        if self.kind == 'NATIVE_JSON':
            if self.pointer is None or self.literal_span is not None:
                raise ValueError('native_operand_needs_pointer')
        elif self.pointer is not None or self.literal_span is None or self.literal_span.source_id != self.source_id:
            raise ValueError('literal_operand_needs_same_source_span')
        return self


class Join(Strict):
    target_pointer: str
    source_pointer: str


class FactCheck(Strict):
    lhs: FactOperand
    operator: Literal['==', '!=', '<', '<=', '>', '>=']
    rhs: FactOperand
    bindings: list[Join]


class WitnessReply(Strict):
    target_id: str
    requirement_id: str
    leaf_id: str
    value: Literal['TRUE', 'FALSE', 'UNKNOWN']
    evidence: list[Span]
    read_requests: list[Span] = Field(max_length=8)
    check: FactCheck | None
    reason: str = Field(min_length=1)

    @model_validator(mode='after')
    def evidence_required(self):
        if self.value != 'UNKNOWN' and (not self.evidence or self.read_requests):
            raise ValueError('resolved_witness_needs_evidence_and_no_open_reads')
        return self


REPLY_TYPES = {'INVENTORY': InventoryReply, 'EFFECT': EffectReply,
               'LINK': LinkReply, 'WITNESS': WitnessReply}

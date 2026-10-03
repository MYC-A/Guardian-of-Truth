from typing import Literal
from pydantic import Field
from guardian_truth.policy_table.schema import Strict

Scalar = str | int | float | bool | None


class Operand(Strict):
    source_id: str
    value: int | float


class Argument(Strict):
    target_source_id: str
    argument: str
    value_source_id: str
    derivation: Literal['COPIED', 'COMPUTED', 'USER_STATED', 'NONE']
    operation: Literal['sum', 'difference', 'percentage', 'ratio'] | None = None
    operands: list[Operand] = Field(default_factory=list)


class Step(Strict):
    clause_id: str
    tool: str
    attempted_in_history: str


class NativeTransfer(Strict):
    target_source_id: str
    permitted_steps: list[Step]


class TextFact(Strict):
    target_source_id: str
    act: Literal['REFUSE', 'TRANSFER', 'ASK_CONFIRM', 'ASK_CLARIFY', 'ASK_USER_ACTION',
                 'OFFER_FUTURE', 'OFFER_ESCALATION', 'ASSERT_DONE', 'ASSERT_FACT', 'UNKNOWN']
    performer: Literal['ASSISTANT', 'USER', 'OTHER', 'UNKNOWN']
    asked_field: str | None = None
    asked_value: Scalar = None
    already_known_at: str = 'NONE'
    known_path: str | None = None
    entity_arguments: dict[str, Scalar] = Field(default_factory=dict)
    permitted_steps: list[Step] = Field(default_factory=list)


class Audit(Strict):
    arguments: list[Argument]
    text_acts: list[TextFact]
    native_transfer_steps: list[NativeTransfer] = Field(default_factory=list)

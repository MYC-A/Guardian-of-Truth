"""Strict application-authored call/result bindings layered over frozen T1.

No automatic contract discovery or tool-name inference occurs here. A generic
operation status is meaningful only under an independently supplied T1 contract.
"""

from dataclasses import asdict, dataclass

from .integrity import digest
from .tools import ContractRegistry, ToolSemantics, TrustedContract, evaluate_t1, read_path
from .types import EffectStatus, Reason


@dataclass(frozen=True)
class FieldEquality:
    argument_path: tuple[str, ...]
    result_path: tuple[str, ...]

    def __post_init__(self):
        if (not self.argument_path or not self.result_path
                or any(not isinstance(part, str) or not part
                       for part in (*self.argument_path, *self.result_path))):
            raise ValueError("exact argument/result field paths required")


@dataclass(frozen=True)
class BoundContract:
    t1: TrustedContract
    result_bindings: tuple[FieldEquality, ...]

    def __post_init__(self):
        if (not isinstance(self.t1, TrustedContract) or not self.result_bindings
                or any(not isinstance(item, FieldEquality) for item in self.result_bindings)):
            raise ValueError("authoritative T1 and explicit call/result joins required")

    @property
    def sha256(self):
        return digest({"t1_sha256": self.t1.sha256,
                       "result_bindings": [asdict(item) for item in self.result_bindings]})


class BoundRegistry:
    def __init__(self, contracts: tuple[BoundContract, ...]):
        if type(contracts) is not tuple or any(not isinstance(item, BoundContract) for item in contracts):
            raise TypeError("immutable application-authored bound contracts required")
        self.contracts = contracts
        self.t1 = ContractRegistry(tuple(item.t1 for item in contracts))
        self.by_identity = {item.t1.identity: item for item in contracts}

    @property
    def sha256(self):
        return digest([item.sha256 for item in self.contracts])


def evaluate_bound_t1(registry: BoundRegistry, call, result) -> ToolSemantics:
    """Require source order, true tool output and exact call/result entity joins."""
    if (call.kind != "call" or call.actor not in {"assistant", "user"}
            or result.kind != "result" or result.actor != "tool"
            or result.source.document != "prompt" or result.index <= call.index
            or call.pairing_issue or result.pairing_issue):
        return ToolSemantics((), EffectStatus.UNKNOWN_EFFECT, (Reason.SOURCE_UNBOUND,))
    bound = registry.by_identity.get(call.tool)
    if bound is None:
        return ToolSemantics((), EffectStatus.UNKNOWN_EFFECT, (Reason.TOOL_EFFECT_UNKNOWN,))
    arguments, payload = call.payload, result.payload
    for binding in bound.result_bindings:
        left, left_present = read_path(arguments, binding.argument_path)
        right, right_present = read_path(payload, binding.result_path)
        if not left_present or not right_present or type(left) is not type(right) or left != right:
            return ToolSemantics((), EffectStatus.UNKNOWN_EFFECT, (Reason.ENTITY_UNBOUND,))
    return evaluate_t1(registry.t1, call, result)

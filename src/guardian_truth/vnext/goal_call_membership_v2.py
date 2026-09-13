"""A candidate allowed-tool set versus ONE observed invocation, never its effect."""

from dataclasses import dataclass

from .types import EntityRef, Reason, Truth


@dataclass(frozen=True)
class GoalCallMembershipAtom:
    atom_id: str
    source_id: str
    entity: EntityRef
    actor: str
    time_index: int
    call_id: str
    allowed_tools: tuple[str, ...]

    def __post_init__(self):
        if (not self.atom_id or not self.source_id or not isinstance(self.entity, EntityRef)
                or type(self.time_index) is not int or self.time_index < 0 or not self.call_id
                or self.actor not in {"assistant", "user", "entity"}
                or len(set(self.allowed_tools)) != len(self.allowed_tools)
                or any(not isinstance(name, str) or not name for name in self.allowed_tools)):
            raise ValueError("exact typed invocation and distinct candidate tool set required")


@dataclass(frozen=True)
class GoalCallMembershipProof:
    atom: GoalCallMembershipAtom
    value: Truth
    supports: tuple[str, ...]
    refutes: tuple[str, ...]
    reasons: tuple[Reason, ...] = ()


def prove_call_membership(atom, ledger):
    unknown = GoalCallMembershipProof(atom, Truth.UNKNOWN, (), (), (Reason.ENTITY_UNBOUND,))
    if atom.time_index >= len(ledger.events):
        return unknown
    event = ledger.events[atom.time_index]
    if (event.kind != "call" or event.source.document != "response" or event.tool is None
            or event.actor != atom.actor or event.actor == "unknown" or event.call_id != atom.call_id
            or atom.entity != EntityRef("event_id", event.event_id, "ledger")):
        return unknown
    value = Truth.TRUE if event.tool.name in atom.allowed_tools else Truth.FALSE
    return GoalCallMembershipProof(atom, value, (event.event_id,) if value is Truth.TRUE else (),
                                    (event.event_id,) if value is Truth.FALSE else ())

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Source:
    """Character offsets in the original, unmodified prompt or response."""

    document: str
    start: int
    end: int


@dataclass
class Event:
    role: str
    kind: str
    text: str
    source: Source
    name: str | None = None
    value: Any = None
    json_valid: bool = False


@dataclass
class FieldSpec:
    name: str
    kind: str
    required: bool
    source: Source
    enum: list[str] = field(default_factory=list)
    children: list["FieldSpec"] = field(default_factory=list)


@dataclass
class ToolSpec:
    name: str
    source: Source
    fields: list[FieldSpec] = field(default_factory=list)
    schema_understood: bool = True


@dataclass
class Catalog:
    tools: dict[str, ToolSpec]
    source: Source | None
    complete: bool
    issues: list[str]


@dataclass
class Finding:
    code: str
    message: str
    sources: list[Source]
    # Only mechanically established, material violations get this status.
    status: str = "violation"


@dataclass
class Observation:
    event: int
    tool: str
    path: list[str | int]
    value: Any
    source: Source


@dataclass
class Obligation:
    kind: str
    source: Source
    checks: list[str]
    status: str = "unknown"


@dataclass(frozen=True)
class EntityKey:
    field: str
    value: Any


@dataclass
class FactNode:
    """An observation, not an assertion of truth or current world state."""

    id: str
    event: int
    tool: str
    role: str
    path: list[str | int]
    field: str
    value: Any
    entities: list[EntityKey]
    sources: list[Source]
    versioned: bool
    previous: list[str] = field(default_factory=list)


@dataclass
class ArgumentTrace:
    event: int
    path: list[str | int]
    value: Any
    entities: list[EntityKey]
    source: Source
    status: str
    supporting: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    truncated: bool = False


@dataclass
class EvidenceGraph:
    facts: list[FactNode] = field(default_factory=list)
    arguments: list[ArgumentTrace] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


@dataclass
class Review:
    findings: list[Finding]
    obligations: list[Obligation]
    unresolved: list[str]
    observations: list[Observation]
    evidence: list[Source]
    checks_run: list[str]
    status: str
    probability: float | None = None
    graph: EvidenceGraph = field(default_factory=EvidenceGraph)
    semantic_backend: str = "none"


class SemanticChecker(Protocol):
    """Optional reader, supplied separately after licensing/runtime decisions.

    Its conclusions remain hypotheses until assessed; merely attaching a source
    does not make a language model conclusion a mechanically proven violation.
    """

    def review(self, prompt: str, response: str, evidence: list[Source]) -> list[Finding]: ...

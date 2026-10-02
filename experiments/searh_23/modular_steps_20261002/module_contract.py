"""Shared envelope: source identity, provenance, assumptions and coverage."""
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ModuleResult:
    module: str
    status: str
    checked_object: str
    source_sha256: str
    provenance: str
    coverage: dict = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    supporting_evidence: list[dict] = field(default_factory=list)
    refuting_evidence: list[dict] = field(default_factory=list)
    unknown_reasons: list[str] = field(default_factory=list)
    cost: dict = field(default_factory=dict)
    payload: Any = None

    def json(self):
        if self.status not in {'JUDGED', 'ADVISORY', 'FOLLOWS', 'CONTRADICTS', 'INSUFFICIENT', 'UNKNOWN', 'INVALID', 'BLOCKED'}:
            raise ValueError('invalid_module_status')
        return asdict(self)

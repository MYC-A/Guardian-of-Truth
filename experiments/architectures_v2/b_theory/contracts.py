"""Transport contracts for independent, source-grounded policy theories."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class Variant(str, Enum):
    B0 = "b0_independent_theories"
    B1 = "b1_source_grounded"
    B2 = "b2_clause_coverage"
    B3 = "b3_mutual_repair"


class AccountStatus(str, Enum):
    ACCOUNTED_FOR = "accounted_for"
    NON_POLICY = "non_policy_with_reason"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    text: str
    document: str = "prompt"
    document_start: int = 0

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "SourceDocument":
        source_id, text = value.get("source_id"), value.get("text")
        document = value.get("document", "prompt")
        document_start = value.get("document_start", value.get("start_char", 0))
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("source_id must be a non-empty string")
        if not isinstance(text, str):
            raise ValueError(f"{source_id}: source text must be a string")
        if document not in {"prompt", "response"}:
            raise ValueError(f"{source_id}: document must be prompt or response")
        if not isinstance(document_start, int) or document_start < 0:
            raise ValueError(f"{source_id}: document_start must be non-negative")
        return cls(source_id, text, document, document_start)


@dataclass(frozen=True)
class SourceLink:
    source_id: str
    start: int
    end: int
    quote: str

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "SourceLink":
        try:
            link = cls(str(value["source_id"]), int(value["start"]),
                       int(value["end"]), str(value["quote"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid source link") from exc
        if link.start < 0 or link.end < link.start:
            raise ValueError("source link offsets are invalid")
        return link


@dataclass(frozen=True)
class Clause:
    clause_id: str
    link: SourceLink

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "Clause":
        clause_id = value.get("clause_id")
        if not isinstance(clause_id, str) or not clause_id:
            raise ValueError("clause_id must be a non-empty string")
        return cls(clause_id, SourceLink.parse(value))


@dataclass(frozen=True)
class TheoryElement:
    element_id: str
    interpretation: str
    source_links: tuple[SourceLink, ...]
    rule_ir: Mapping[str, Any] | None
    unresolved_components: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "TheoryElement":
        element_id, interpretation = value.get("element_id"), value.get("interpretation")
        wire = value.get("wire_candidate")
        if isinstance(wire, Mapping):
            element_id = element_id or wire.get("candidate_id")
            interpretation = interpretation or "donor RuleIR candidate"
        if not isinstance(element_id, str) or not element_id:
            raise ValueError("element_id must be a non-empty string")
        if not isinstance(interpretation, str) or not interpretation:
            raise ValueError(f"{element_id}: interpretation must be non-empty")
        links = value.get("source_links", [])
        if not isinstance(links, list):
            raise ValueError(f"{element_id}: source_links must be a list")
        if wire is not None:
            if not isinstance(wire, Mapping):
                raise ValueError(f"{element_id}: wire_candidate must be an object")
            rule_ir = wire.get("rule")
            raw_links = wire.get("source_spans", [])
            if not links and isinstance(raw_links, list):
                links = [{"source_id": item.get("segment_id"), "start": item.get("start"),
                          "end": item.get("end"), "quote": item.get("quote")}
                         for item in raw_links if isinstance(item, Mapping)]
            unresolved = wire.get("unresolved_components", [])
        else:
            rule_ir = value.get("rule_ir")
            unresolved = value.get("unresolved_components", [])
        if rule_ir is not None and not isinstance(rule_ir, Mapping):
            raise ValueError(f"{element_id}: rule_ir must be an object")
        if not isinstance(unresolved, list) or not all(isinstance(x, str) for x in unresolved):
            raise ValueError(f"{element_id}: unresolved_components must be strings")
        return cls(element_id, interpretation,
                   tuple(SourceLink.parse(item) for item in links), rule_ir,
                   tuple(unresolved))


@dataclass(frozen=True)
class ClauseAccount:
    clause_id: str
    status: AccountStatus
    element_ids: tuple[str, ...] = ()
    reason: str | None = None

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "ClauseAccount":
        clause_id = value.get("clause_id")
        if not isinstance(clause_id, str) or not clause_id:
            raise ValueError("clause account requires clause_id")
        try:
            status = AccountStatus(value["status"])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"{clause_id}: invalid account status") from exc
        element_ids = value.get("element_ids", [])
        if not isinstance(element_ids, list) or not all(isinstance(x, str) for x in element_ids):
            raise ValueError(f"{clause_id}: element_ids must be strings")
        reason = value.get("reason")
        if status is AccountStatus.NON_POLICY and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError(f"{clause_id}: non-policy status requires a reason")
        return cls(clause_id, status, tuple(element_ids), reason)


@dataclass(frozen=True)
class TheoryCandidate:
    candidate_id: str
    provider: str
    elements: tuple[TheoryElement, ...]
    clause_accounts: tuple[ClauseAccount, ...] = ()
    parent_candidate_id: str | None = None

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "TheoryCandidate":
        candidate_id, provider = value.get("candidate_id"), value.get("provider")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("candidate_id must be a non-empty string")
        if not isinstance(provider, str) or not provider:
            raise ValueError(f"{candidate_id}: provider must be a non-empty string")
        elements, accounts = value.get("elements", []), value.get("clause_accounts", [])
        if not isinstance(elements, list) or not isinstance(accounts, list):
            raise ValueError(f"{candidate_id}: elements/accounts must be lists")
        parent = value.get("parent_candidate_id")
        if parent is not None and not isinstance(parent, str):
            raise ValueError(f"{candidate_id}: parent_candidate_id must be a string")
        parsed = cls(candidate_id, provider,
                     tuple(TheoryElement.parse(item) for item in elements),
                     tuple(ClauseAccount.parse(item) for item in accounts), parent)
        ids = [item.element_id for item in parsed.elements]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{candidate_id}: duplicate element_id")
        clause_ids = [item.clause_id for item in parsed.clause_accounts]
        if len(clause_ids) != len(set(clause_ids)):
            raise ValueError(f"{candidate_id}: duplicate clause account")
        return parsed


@dataclass(frozen=True)
class CaseInput:
    case_id: str
    sources: tuple[SourceDocument, ...]
    clauses: tuple[Clause, ...]

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "CaseInput":
        case_id = value.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("case_id must be a non-empty string")
        sources, clauses = value.get("sources", []), value.get("clauses", [])
        if not isinstance(sources, list) or not isinstance(clauses, list):
            raise ValueError(f"{case_id}: sources/clauses must be lists")
        parsed = cls(case_id, tuple(SourceDocument.parse(x) for x in sources),
                     tuple(Clause.parse(x) for x in clauses))
        if len({x.source_id for x in parsed.sources}) != len(parsed.sources):
            raise ValueError(f"{case_id}: duplicate source_id")
        if len({x.clause_id for x in parsed.clauses}) != len(parsed.clauses):
            raise ValueError(f"{case_id}: duplicate clause_id")
        return parsed

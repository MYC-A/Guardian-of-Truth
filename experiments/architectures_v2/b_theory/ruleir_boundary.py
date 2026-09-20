"""Conservative boundary to the existing RuleIR and proof pipeline."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import SourceDocument, TheoryElement
from .grounding import validate_link

_SEMANTIC = Path(__file__).resolve().parents[2] / "semantic_pipeline_v1"
if str(_SEMANTIC) not in sys.path:
    sys.path.insert(0, str(_SEMANTIC))

from rule_ir import (Atom, Cardinality, Comparison, ConditionNode, Provenance, Ref,
                     RuleIR, SourceSpan, Temporal)  # noqa: E402

from guardian_truth.semantic_pipeline_v1.rule_ir import rule_from_dict as donor_rule_from_dict
from guardian_truth.semantic_pipeline_v1.types import RuleExpression, RuleTerm


@dataclass(frozen=True)
class BoundaryResult:
    status: str
    reason: str
    rule: RuleIR | None = None


def prepare_rule_ir(element: TheoryElement,
                    sources: dict[str, SourceDocument]) -> BoundaryResult:
    """Validate an extracted hypothesis without admitting it as a premise.

    A valid result still requires the existing binder before it can reach
    ``compile_rule_set``/Clingo. Exact provenance establishes attribution,
    not semantic truth.
    """
    if element.rule_ir is None:
        return BoundaryResult("UNREPRESENTABLE", "NO_RULE_IR")
    if not element.source_links:
        return BoundaryResult("REJECTED", "UNANCHORED")
    for link in element.source_links:
        valid, reason = validate_link(link, sources)
        if not valid:
            return BoundaryResult("REJECTED", reason)
    try:
        donor_rule = donor_rule_from_dict(dict(element.rule_ir))
        rule = _to_fullarch_rule(element, donor_rule, sources)
    except NotImplementedError as exc:
        return BoundaryResult("UNREPRESENTABLE", str(exc))
    except Exception as exc:  # validators expose different base errors.
        return BoundaryResult("REJECTED", f"RULE_IR_INVALID:{type(exc).__name__}")

    declared = {(sources[link.source_id].document,
                 sources[link.source_id].document_start + link.start,
                 sources[link.source_id].document_start + link.end, link.quote)
                for link in element.source_links}
    for span in rule.source_spans:
        if (span.document, span.start, span.end, span.quote) not in declared:
            return BoundaryResult("REJECTED", "RULE_IR_SPAN_NOT_IN_PROVENANCE")
    if not rule.source_spans:
        return BoundaryResult("REJECTED", "RULE_IR_HAS_NO_SOURCE_SPANS")
    return BoundaryResult(
        "BINDING_REQUIRED",
        "STRUCTURALLY_VALID_HYPOTHESIS; run existing binder/compiler; not a trusted premise",
        rule,
    )


def _ref(term: RuleTerm) -> Ref:
    if term.kind not in {"ACTION", "STATE", "CLAIM"}:
        raise NotImplementedError(f"EXTRACTED_BUT_IR_UNREPRESENTABLE:target:{term.kind}")
    text = term.name
    if not isinstance(text, str) or not text:
        raise NotImplementedError("EXTRACTED_BUT_IR_UNREPRESENTABLE:unnamed-term")
    return Ref(kind=term.kind, text=text, ref=text)


def _atom(term: RuleTerm) -> Atom:
    ref = _ref(term)
    return Atom(kind=term.kind, text=ref.text, ref=ref.ref)


def _expression(value: RuleExpression | None) -> ConditionNode | None:
    if value is None:
        return None
    if value.operator == "ATOM" and value.term is not None:
        return ConditionNode(atom=_atom(value.term))
    if value.operator in {"AND", "OR"}:
        children = [_expression(child) for child in value.operands]
        if any(child is None for child in children):
            raise NotImplementedError("EXTRACTED_BUT_IR_UNREPRESENTABLE:empty-expression")
        return (ConditionNode(all=children) if value.operator == "AND"
                else ConditionNode(any=children))
    if value.operator == "NOT" and len(value.operands) == 1:
        child = _expression(value.operands[0])
        if child is None:
            raise NotImplementedError("EXTRACTED_BUT_IR_UNREPRESENTABLE:empty-not")
        return ConditionNode(**{"not": child})
    if value.operator == "COMPARE" and value.left and value.right:
        lhs = _ref(value.left)
        if value.right.value is None:
            raise NotImplementedError("EXTRACTED_BUT_IR_UNREPRESENTABLE:comparison-rhs")
        import json
        comparison = Comparison(lhs=lhs, op=value.comparator,
                                rhs_literal=json.dumps(value.right.value, ensure_ascii=False))
        return ConditionNode(atom=Atom(kind=value.left.kind, text=lhs.text, ref=lhs.ref,
                                       comparison=comparison))
    if value.operator == "CARDINALITY" and value.term and value.count is not None:
        subject = _ref(value.term)
        op = {"EXACT": "EXACTLY", "MIN": "AT_LEAST", "MAX": "AT_MOST"}.get(
            value.cardinality)
        if op is None:
            raise NotImplementedError("EXTRACTED_BUT_IR_UNREPRESENTABLE:cardinality")
        cardinality = Cardinality(subject=subject, op=op, count=value.count)
        return ConditionNode(atom=Atom(kind=value.term.kind, text=subject.text,
                                       ref=subject.ref, cardinality=cardinality))
    raise NotImplementedError(f"EXTRACTED_BUT_IR_UNREPRESENTABLE:expression:{value.operator}")


def _to_fullarch_rule(element: TheoryElement, donor_rule, sources) -> RuleIR:
    if donor_rule.temporal != "NONE":
        # Donor RuleIR has no explicit temporal anchor, while FullArch requires one.
        raise NotImplementedError("EXTRACTED_BUT_IR_UNREPRESENTABLE:temporal-anchor")
    conditions = _expression(donor_rule.condition)
    exceptions = []
    if donor_rule.exception is not None:
        converted = _expression(donor_rule.exception)
        if converted is not None:
            exceptions.append(converted)
    # Some extraction templates place the single UNLESS operand in `condition`
    # instead of `exception`.  In that unambiguous shape it is an exemption,
    # never an additional prerequisite to the prohibition/requirement.
    if donor_rule.relation == "UNLESS" and not exceptions and conditions is not None:
        exceptions.append(conditions)
        conditions = None
    if donor_rule.relation == "UNLESS" and not exceptions:
        raise NotImplementedError("EXTRACTED_BUT_IR_UNREPRESENTABLE:unless-without-exception")
    extractor = "deterministic"
    # Preserve the producer class while satisfying the frozen experimental enum.
    lowered_provider = element.element_id.casefold()
    if "mistral" in lowered_provider:
        extractor = "mistral"
    elif "nuextract" in lowered_provider:
        extractor = "nuextract"
    elif "gliner" in lowered_provider:
        extractor = "gliner2"
    spans = []
    for link in element.source_links:
        source = sources[link.source_id]
        spans.append(SourceSpan(document=source.document,
                                start=source.document_start + link.start,
                                end=source.document_start + link.end, quote=link.quote))
    unresolved = list(donor_rule.unresolved_references)
    unresolved.extend(element.unresolved_components)
    return RuleIR(
        rule_id=element.element_id,
        modality=donor_rule.modality,
        target=_ref(donor_rule.target),
        conditions=conditions,
        exceptions=exceptions,
        temporal=Temporal(relation="NONE"),
        actor=donor_rule.subject or "UNKNOWN",
        source_spans=spans,
        provenance=Provenance(extractor=extractor),
        unresolved=list(dict.fromkeys(unresolved)),
    )


def serialise_boundary(result: BoundaryResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "reason": result.reason,
        "rule_ir": (result.rule.model_dump(by_alias=True, exclude_none=True)
                    if result.rule is not None else None),
    }

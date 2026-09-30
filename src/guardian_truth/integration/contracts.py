"""Acquire only explicitly documented, source-scoped result contracts.

Tool names, free-text descriptions and model confidence never authorize a
WorldFact here. A catalog's structured ``documented_contracts`` declarations
are an application-supplied source of semantics; all other result fields stay
observations without business predicates. This is a narrow automatic path,
not a natural-language contract parser.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from guardian_truth.step2.result_types import json_path_get, scalar_to_json
from guardian_truth.step2.trusted import ReviewedBinding, assess, producer_scope
from guardian_truth.step2.types import Authority, EffectStrength
from guardian_truth.step2.verifier import CandidateFact, TrajectoryCase


_FIELD = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")


@dataclass(frozen=True)
class ContractAcquisition:
    bindings: tuple[ReviewedBinding, ...]
    issues: tuple[str, ...]


def acquire_documented(case: TrajectoryCase) -> ContractAcquisition:
    """Validate literal catalog declarations and bind them to catalog slots.

    ``DOC_EXPLICIT`` means the application supplied this structured contract;
    it must never be set from an LLM's paraphrase of a tool description.
    Invalid or ambiguous declarations are omitted with auditable reasons.
    """
    bindings: list[ReviewedBinding] = []
    issues: list[str] = []
    for slot, item in enumerate(case.tools):
        name = item.get("name")
        producer = producer_scope(case, name) if isinstance(name, str) else None
        if producer is None:
            issues.append(f"catalog:{slot}:producer_not_unique")
            continue
        declarations = item.get("documented_contracts", ())
        if not isinstance(declarations, (tuple, list)):
            issues.append(f"catalog:{slot}:invalid_contract_container")
            continue
        parameters = item.get("parameters", {})
        schema = item.get("result_schema", {})
        if not isinstance(parameters, dict) or not isinstance(schema, dict):
            issues.append(f"catalog:{slot}:schema_not_structured")
            continue
        for number, declaration in enumerate(declarations):
            ref = f"catalog:{slot}:contract:{number}"
            if not isinstance(declaration, dict):
                issues.append(ref + ":not_object")
                continue
            entity = declaration.get("entity_argument")
            echo = declaration.get("result_entity_path")
            path = declaration.get("result_value_path")
            predicate = declaration.get("predicate")
            strength = declaration.get("strength")
            values = declaration.get("allowed_values")
            if (not isinstance(entity, str) or not _FIELD.fullmatch(entity)
                    or entity not in parameters or echo != f"$.{entity}"):
                issues.append(ref + ":entity_scope_unlicensed")
                continue
            if (not isinstance(path, str) or not path.startswith("$.")
                    or not _FIELD.fullmatch(path[2:]) or path[2:] not in schema
                    or entity not in schema):
                issues.append(ref + ":result_path_unlicensed")
                continue
            if not isinstance(predicate, str) or not predicate.strip():
                issues.append(ref + ":predicate_missing")
                continue
            entity_type = declaration.get("entity_type")
            if entity_type is None:
                # Syntactic fallback only when the declared predicate agrees
                # with the ID field's namespace. Never guess an alias.
                entity_type = entity.removesuffix("_id")
                if not predicate.startswith(entity_type + "."):
                    issues.append(ref + ":entity_type_not_explicit")
                    continue
            if not isinstance(entity_type, str) or not _FIELD.fullmatch(entity_type):
                issues.append(ref + ":entity_type_invalid")
                continue
            try:
                typed_strength = EffectStrength(strength)
            except (ValueError, TypeError):
                issues.append(ref + ":strength_invalid")
                continue
            if (not isinstance(values, (list, tuple))
                    or any(scalar_to_json(v) is None for v in values)):
                issues.append(ref + ":values_invalid")
                continue
            if typed_strength is not EffectStrength.OBSERVED and not values:
                issues.append(ref + ":effect_values_missing")
                continue
            authority = (Authority.READ_OBSERVATION
                         if typed_strength is EffectStrength.OBSERVED
                         else Authority.CONTRACT_GUARANTEE)
            try:
                bindings.append(ReviewedBinding(
                    producer, predicate, entity_type,
                    entity, echo, path, typed_strength, authority,
                    tuple(scalar_to_json(v) for v in values),
                    "DOC_EXPLICIT", ref))
            except (TypeError, ValueError):
                issues.append(ref + ":binding_rejected")
    return ContractAcquisition(tuple(bindings), tuple(issues))


def facts_from_documented(case: TrajectoryCase) -> tuple[list, list, tuple[str, ...]]:
    """Use documented bindings to propose exact result values for trusted.assess.

    Returns (VerifiedFact list, Assessment list, acquisition issues). Missing
    bindings never create a business fact. Every candidate is checked again
    against transport pairing, entity echo, JSON value, and contract scope.
    """
    acquired = acquire_documented(case)
    verified = []
    assessments = []
    by_call: dict[str, list] = {}
    for result in case.results:
        by_call.setdefault(result.call_id, []).append(result)
    for call in case.calls:
        producer = producer_scope(case, call.tool)
        if producer is None or not isinstance(call.payload, dict):
            continue
        for result in by_call.get(call.call_id, ()):
            for binding in acquired.bindings:
                if binding.producer != producer:
                    continue
                value, present = json_path_get(result.payload, binding.result_path)
                if not present:
                    continue
                rendered = scalar_to_json(value)
                if rendered is None:
                    continue
                if binding.allowed_values and rendered not in binding.allowed_values:
                    continue
                entity = call.payload.get(binding.entity_field)
                if entity is None:
                    continue
                candidate = CandidateFact(
                    binding.predicate, binding.entity_type, binding.entity_field,
                    str(entity), rendered, binding.result_path, binding.strength)
                assessment = assess(case, call, result, candidate,
                                    acquired.bindings)
                assessments.append(assessment)
                if assessment.verified is not None:
                    verified.append(assessment.verified)
    # Identical declarations should not double-count one fact.
    unique = {json.dumps(v.as_dict(), sort_keys=True): v for v in verified}
    return list(unique.values()), assessments, acquired.issues

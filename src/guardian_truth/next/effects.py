"""Tool-effect registry.  Schemas describe inputs, never successful effects."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from guardian_truth.parsing import parse_catalog, parse_events

from .records import FourValue, ToolEffectContract


def schema_registry(prompt: str) -> dict[str, ToolEffectContract]:
    events = parse_events(prompt, "prompt")
    catalog = parse_catalog(events, prompt)
    result = {}
    for name, spec in catalog.tools.items():
        entity_fields = tuple(sorted(
            field.name for field in spec.fields
            if field.name == "id" or field.name.endswith("_id")
        ))
        result[name] = ToolEffectContract(
            tool=name,
            entity_fields=entity_fields,
            provenance="T0_schema_name",
        )
    return result


def merge_human_contracts(
    base: dict[str, ToolEffectContract],
    overrides: dict[str, ToolEffectContract],
) -> dict[str, ToolEffectContract]:
    merged = dict(base)
    for name, contract in overrides.items():
        if name != contract.tool:
            raise ValueError("contract key/tool mismatch")
        merged[name] = replace(contract, provenance="T1_human_contract")
    return merged


def failure_proves_no_effect(contract: ToolEffectContract) -> bool:
    return contract.failure_no_effect is FourValue.TRUE


def load_human_contracts(path: Path) -> dict[str, ToolEffectContract]:
    """Load a reviewed T1 registry; reject extra fields and weak provenance."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "contracts"}:
        raise ValueError("invalid contract registry")
    if payload["schema_version"] != "guardian-tool-effects-v1" or not isinstance(payload["contracts"], list):
        raise ValueError("unsupported contract registry")
    expected = {"tool", "tool_version", "inputs", "preconditions", "success_predicate",
                "guaranteed_effects", "possible_effects", "failure_no_effect",
                "reads", "writes", "entity_fields", "freshness", "idempotent",
                "entity_key_mapping", "provenance_transform", "evidence_source", "provenance"}
    result = {}
    for row in payload["contracts"]:
        if not isinstance(row, dict) or set(row) != expected:
            raise ValueError("invalid contract fields")
        text_fields = ("tool", "tool_version", "freshness", "provenance_transform",
                       "evidence_source", "provenance")
        list_fields = ("inputs", "preconditions", "success_predicate", "guaranteed_effects",
                       "possible_effects", "reads", "writes", "entity_fields")
        if (not all(isinstance(row[key], str) and row[key] for key in text_fields)
                or not all(isinstance(row[key], list)
                           and all(isinstance(item, str) and item for item in row[key])
                           for key in list_fields)
                or not isinstance(row["entity_key_mapping"], dict)
                or not all(isinstance(key, str) and key and isinstance(value, str) and value
                           for key, value in row["entity_key_mapping"].items())
                or row["evidence_source"] not in {"HUMAN_SIGNED", "TESTED", "DOC_EXPLICIT"}
                or not row["provenance"].startswith("T1:")):
            raise ValueError("invalid contract values")
        try:
            failure = FourValue(row["failure_no_effect"])
            idempotent = FourValue(row["idempotent"])
        except ValueError:
            raise ValueError("invalid four-valued contract field") from None
        contract = ToolEffectContract(
            tool=row["tool"], tool_version=row["tool_version"], inputs=tuple(row["inputs"]),
            preconditions=tuple(row["preconditions"]),
            success_predicate=tuple(row["success_predicate"]),
            guaranteed_effects=tuple(row["guaranteed_effects"]),
            possible_effects=tuple(row["possible_effects"]), failure_no_effect=failure,
            reads=tuple(row["reads"]), writes=tuple(row["writes"]),
            entity_fields=tuple(row["entity_fields"]), freshness=row["freshness"],
            idempotent=idempotent,
            entity_key_mapping=tuple(sorted(row["entity_key_mapping"].items())),
            provenance_transform=row["provenance_transform"],
            evidence_source=row["evidence_source"], provenance=row["provenance"],
        )
        if contract.tool in result:
            raise ValueError("duplicate tool contract")
        result[contract.tool] = contract
    return result

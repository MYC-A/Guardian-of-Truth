"""Tool-effect registry.  Schemas describe inputs, never successful effects."""

from __future__ import annotations

from dataclasses import replace

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

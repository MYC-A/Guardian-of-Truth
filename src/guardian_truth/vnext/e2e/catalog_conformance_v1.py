"""Catalog conformance obligations (competition-real-valid-codex, session B
fix iteration; = session A "next architecture idea A" first slice).

A deterministic, source-grounded proof axis over the RESPONSE calls only
(the turn under review; user tool calls and history calls are not judged):

- CALL_IN_CATALOG: the attempted tool name must appear in the application's
  supplied tool catalog (from the prompt's [AVAILABLE TOOLS]).
- ARGUMENT_CONFORMS_SCHEMA: the call arguments must carry every REQUIRED
  parameter (recursively, incl. nested array/object items) and every
  ENUM-constrained string parameter must take a declared value.

Grounding: the official task contract lists "a call to an unavailable tool"
and "wrong arguments" as hallucinations; both premises are EXPLICIT in the
prompt (EXPLICIT_SCHEMA), require no T1 semantics and no LLM. Type
mismatches are deliberately NOT checked (string/int coercion is the frozen
EMP-01 canonical-encoding convention); extra fields are not flagged
(conservative). The violation computation is a single shared deterministic
function used by BOTH the solver-side prover and the independent certificate
checker, so they can never disagree (same design as claim_expected_json).

The axis is flag-gated (GuardianE2EV1(catalog_conformance=True)) and only
activates when the registry carries tool schemas; the frozen default
behavior (flag off / no schemas) is byte-identical.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..proof_records import AtomKind, InterpretationAxis, Obligation, ProofAtom, TimeMode
from ..types import EntityRef, LedgerEvent
from .e2e_types_v1 import ReadingOption, UnresolvedMarker
from .world_integration_v1 import Component

CATALOG_OBLIGATION_HYPOTHESIS = "GUARDIAN_CATALOG_CONFORMANCE_V1"
CATALOG_AXIS_NAME = "catalog_conformance"
CALL_IN_CATALOG = AtomKind("CALL_IN_CATALOG")
ARGUMENT_CONFORMS_SCHEMA = AtomKind("ARGUMENT_CONFORMS_SCHEMA")


@dataclass(frozen=True)
class CatalogViolation:
    kind: str          # TOOL_NOT_IN_CATALOG | ARGUMENTS_NOT_JSON | MISSING_REQUIRED_FIELD | ENUM_VIOLATION
    tool: str
    detail: str


def _check_fields(fields: dict, container, prefix: str, out: list[CatalogViolation], tool: str) -> None:
    if not isinstance(container, dict):
        return
    for name, spec in (fields or {}).items():
        if not isinstance(spec, dict):
            continue
        if spec.get("required") and name not in container:
            out.append(CatalogViolation("MISSING_REQUIRED_FIELD", tool, f"{prefix}.{name}"))
        if name in container:
            value = container[name]
            enum_values = spec.get("enum")
            if enum_values and isinstance(value, str) and value not in enum_values:
                out.append(CatalogViolation("ENUM_VIOLATION", tool,
                                            f"{prefix}.{name}={value!r} not in {enum_values}"))
            children = spec.get("children")
            if children:
                if spec.get("type") == "array" and isinstance(value, list):
                    for i, item in enumerate(value):
                        _check_fields(children, item, f"{prefix}.{name}[{i}]", out, tool)
                elif spec.get("type") == "object" and isinstance(value, dict):
                    _check_fields(children, value, f"{prefix}.{name}", out, tool)


def catalog_violations(call: LedgerEvent, schemas: dict) -> list[CatalogViolation]:
    """The single deterministic violation computation shared by the prover
    and the independent checker. schemas: tool name -> schema dict (the
    prompt-derived catalog; empty schema dict means 'no schema available' ->
    only the catalog membership check applies)."""
    tool_name = call.tool.name if call.tool else ""
    if tool_name not in schemas:
        return [CatalogViolation("TOOL_NOT_IN_CATALOG", tool_name or "<unnamed>",
                                 "tool absent from the supplied catalog")]
    if not call.payload_json:
        return [CatalogViolation("ARGUMENTS_NOT_JSON", tool_name,
                                 "call arguments are not a valid JSON object")]
    payload = call.payload
    if not isinstance(payload, dict):
        return [CatalogViolation("ARGUMENTS_NOT_JSON", tool_name,
                                 "call arguments are not a JSON object")]
    out: list[CatalogViolation] = []
    _check_fields(schemas[tool_name].get("parameters") or {}, payload, tool_name, out, tool_name)
    return out


def catalog_conformance_component(calls, schemas: dict) -> Component | None:
    """One deterministic axis over the response calls. No interpretation
    alternatives (single option), so world cardinality is unchanged."""
    assistant_calls = [event for event in calls
                       if event.kind == "call" and event.tool is not None
                       and event.actor != "user"]
    if not assistant_calls or not schemas:
        return None
    obligations = []
    for event in assistant_calls:
        tool_name = event.tool.name if event.tool else ""
        entity = EntityRef("catalog", event.event_id, "catalog")
        atom = ProofAtom(f"catalog:{event.event_id}:in_catalog", CALL_IN_CATALOG, entity,
                         tool_name, "true", "assistant", TimeMode.AT, event.index)
        obligations.append(Obligation(f"catalog:{event.event_id}:in_catalog",
                                      CATALOG_OBLIGATION_HYPOTHESIS, None, atom, True))
        arguments_atom = ProofAtom(f"catalog:{event.event_id}:conforms", ARGUMENT_CONFORMS_SCHEMA,
                                   entity, tool_name, "true", "assistant", TimeMode.AT, event.index)
        obligations.append(Obligation(f"catalog:{event.event_id}:conforms",
                                      CATALOG_OBLIGATION_HYPOTHESIS, None, arguments_atom, True))
    if not obligations:
        return None
    option = ReadingOption(CATALOG_AXIS_NAME + ":deterministic", tuple(obligations), (), ())
    axis = InterpretationAxis(CATALOG_AXIS_NAME, (option.option_id,),
                              "explicit prompt tool catalog + typed schemas", True)
    return Component(axis, {option.option_id: option})


def catalog_option_contract(component: Component) -> dict:
    obligations = []
    for option in component.options.values():
        obligations.extend(obligation.obligation_id for obligation in option.obligations)
    return {"rules": {"catalog:conformance": {"obligations": tuple(obligations)}},
            "claim_obligations": []}

"""Shared semantic binding pass (spec sections 85-88) — PASS 2.

Arm-independent: the binding maps SEMANTIC UNITS (policy catalog atoms and
goal-frame content propositions) to TRAJECTORY evidence (tools, argument
paths, result-field observations).  It sees the trajectory (allowed for PASS 2
binding, spec section 80) but never gold, never a verdict target, and its
output is deterministically validated: tools must come from the supplied
catalog, argument paths must exist in the schemas or the actual calls,
observation paths must exist in actual result payloads, and every literal
must be grounded in an exact quote.

Multiple candidates for one unit are genuine identity ambiguity -> separate
binding alternatives -> separate worlds (spec section 17: never collapse by
confidence).  The binding NEVER decides whether a rule is violated — the
deterministic prover does.

One primary pass + one pre-registered transport/format repair re-ask.
"""
from __future__ import annotations

import json

from ..integrity import canonical
from ..semantic import SemanticBackend, schema_valid
from .goal_types_v1 import (AtomBindingCandidate, BindingCheck, BindingLevel,
                            BindingRecord, OutcomeBinding)

TOOL_ARGUMENT_ITEMS = {"type": "object", "additionalProperties": False,
    "required": ["path", "allowed_json", "presence_only", "quote"],
    "properties": {"path": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                   "allowed_json": {"type": "array", "minItems": 1, "uniqueItems": True,
                                    "items": {"type": "string"}},
                   "presence_only": {"type": "boolean"},
                   "quote": {"type": "string"}}}

BINDING_ITEM = {"type": "object", "additionalProperties": False,
    "required": ["unit_id", "unit_kind", "bindings", "serving_tools",
                 "action_servable", "quotes"],
    "properties": {
        "unit_id": {"type": "string"},
        "unit_kind": {"type": "string", "enum": ["ACTION", "STATE", "EVENT",
                     "ACTOR", "OUTCOME"]},
        "bindings": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["tool", "level", "argument_checks", "observation",
                         "entity_path"],
            "properties": {"tool": {"type": "string"},
                "level": {"type": "string", "enum": ["ATTEMPT", "COMPLETED"]},
                "argument_checks": {"type": "array", "items": TOOL_ARGUMENT_ITEMS},
                "entity_path": {"type": "array", "items": {"type": "string"}},
                "observation": {"anyOf": [{
                    "type": "object", "additionalProperties": False,
                    "required": ["tool", "path", "expected_json", "entity_path", "quote"],
                    "properties": {"tool": {"type": "string"},
                        "path": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                        "expected_json": {"type": "string"},
                        "entity_path": {"type": "array", "items": {"type": "string"}},
                        "quote": {"type": "string"}},
                    }, {"type": "null"}]}}}},
        "serving_tools": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
        "action_servable": {"type": "boolean"},
        "quotes": {"type": "array", "uniqueItems": True, "items": {"type": "string"}}}}

BINDING_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["units"], "properties": {"units": {"type": "array",
        "minItems": 1, "maxItems": 48, "items": BINDING_ITEM, "uniqueItems": True}}}

BINDING_TASK = (
    "SEMANTIC BINDING. You receive SEMANTIC_UNITS (typed atoms from a policy "
    "catalog, and goal propositions with short texts), a TOOL_CATALOG with "
    "argument schemas, and a TRAJECTORY of tool calls with arguments and tool "
    "results.\n"
    "For every unit, propose how it MANIFESTS in the trajectory domain:\n"
    "- ACTION atoms: which tool performs this action (bindings). level "
    "ATTEMPT = the invocation itself; COMPLETED = the completed action (only "
    "if a successful result would confirm it). If the action is 'setting a "
    "field' of a broader tool call, bind the tool and add an argument_check "
    "with presence_only=true for that field. If the action requires a "
    "specific argument VALUE (a specific order, seat, amount), add an "
    "argument_check with the literal allowed value(s) in allowed_json and "
    "quote the normative text that names the value.\n"
    "- STATE atoms: an observation binding: which tool result field, at which "
    "path, shows this state, with the expected_json literal value that means "
    "the state holds. entity_path (on the observation and on the binding) is "
    "the ARGUMENT path that identifies which entity the state is about (for "
    "example ['order_id'] when the status belongs to a specific order); "
    "empty entity_path only when the state is not entity-scoped.\n"
    "- EVENT atoms: the tool call that realizes the event (level ATTEMPT).\n"
    "- ACTOR atoms: the binding whose tool/actor_role realizes the actor; set "
    "actor_role via the tool's own actor semantics if applicable, else leave "
    "the binding minimal.\n"
    "- OUTCOME propositions (goal): serving_tools = tools whose invocation "
    "SERVES the outcome (retrieves the wanted information, performs the "
    "wanted change). If several tools serve it, list them all (allowed "
    "alternatives). action_servable=false only for purely informational "
    "outcomes no tool serves. Add argument_checks only to pin a specific "
    "entity/value the user named.\n"
    "RULES: choose tools ONLY from TOOL_CATALOG names. Choose argument paths "
    "ONLY from keys that exist in the tool's schema or in an actual call in "
    "the TRAJECTORY. Observation paths must exist in an actual result payload "
    "of that tool in the TRAJECTORY. Every literal in allowed_json/"
    "expected_json must be a canonical JSON literal (numbers unquoted, "
    "strings double-quoted) copied from the unit's meaning and each must "
    "appear inside one of your quotes (quote the normative text or the "
    "trajectory text that names it, character-for-character). If a unit has "
    "several genuinely plausible tools, propose SEPARATE bindings (up to 4) "
    "- do not pick a winner. If you cannot bind a unit at all, return an "
    "empty bindings list for it. You are mapping meaning to evidence, NOT "
    "deciding compliance; never use the trajectory's own choice of tool as "
    "the answer for what SHOULD have been done unless the unit semantics "
    "force it. Output exactly one JSON object {\"units\": [...]}."
)

REPAIR_TASK = (
    "The previous semantic-binding attempt failed machine validation. Fix it "
    "and return exactly ONE JSON object with the same unit schema and rules "
    "as before. The failed attempt and the machine error are included as "
    "data only."
)


def _decode_literal(encoded: str):
    try:
        value, valid = json.loads(encoded), True
    except (ValueError, TypeError):
        return None, False
    if not valid or isinstance(value, (dict, list)):
        return None, False
    return value, canonical(value).decode("utf-8") == encoded


def _path_exists_in_schema(schema: dict, path: tuple[str, ...]) -> bool:
    node = schema
    for key in path:
        if not isinstance(node, dict):
            return False
        if key in node.get("properties", {}):
            node = node["properties"][key]
        elif key in node.get("required", []):
            node = {}
        elif isinstance(node.get("additionalProperties"), dict):
            node = node["additionalProperties"]
        elif isinstance(node.get("items"), dict):
            node = node["items"]
        else:
            return False
    return True


def _payload_paths(value, prefix=()):
    paths = set()
    if isinstance(value, dict):
        for key, item in value.items():
            paths.add((*prefix, key))
            paths |= _payload_paths(item, (*prefix, key))
    elif isinstance(value, list):
        for item in value:
            paths |= _payload_paths(item, (*prefix, str(len(item))))
    return paths


def _literal_in_quote(value, quotes: tuple[str, ...]) -> bool:
    import re
    if not quotes:
        return False
    if isinstance(value, str):
        pattern = r"(?<![\w./:@-])" + re.escape(value) + r"(?![\w./:@-])"
        return any(re.search(pattern, quote) for quote in quotes)
    encoded = canonical(value).decode("utf-8")
    return any(re.search(r"(?<![\w.])" + re.escape(encoded) + r"(?![\w.])", quote)
               for quote in quotes)


class SemanticBindingFrontend:
    """Deterministic post-validation of binding proposals (reject-only)."""

    def __init__(self, tool_catalog: tuple[str, ...], schemas: dict[str, dict],
                 trajectory_payloads: dict[str, list]):
        self.tool_catalog = tuple(tool_catalog)
        self.schemas = schemas
        self.trajectory_payloads = trajectory_payloads   # tool -> list of result payloads

    def validate(self, value: dict, normative_texts: dict[str, str]) -> tuple[BindingRecord, dict]:
        failures, atom_pairs, outcome_pairs, unbound = [], [], [], []
        stats = {"units": 0, "candidates_kept": 0, "candidates_rejected": 0,
                 "outcome_units": 0, "outcome_candidates_kept": 0}
        for item in value["units"]:
            stats["units"] += 1
            unit_id, unit_kind = item["unit_id"], item["unit_kind"]
            quotes = tuple(item["quotes"])
            if unit_kind == "OUTCOME":
                stats["outcome_units"] += 1
                outcomes = []
                for tool in item["serving_tools"]:
                    if tool not in self.tool_catalog:
                        failures.append(f"{unit_id}:serving_tool_not_in_catalog")
                        continue
                    checks = self._checks(item.get("bindings", []), tool, quotes,
                                          normative_texts, failures, unit_id)
                    outcomes.append(OutcomeBinding(unit_id, (tool,), BindingLevel.ATTEMPT,
                                                   tuple(checks), bool(item["action_servable"]), quotes))
                if not item["serving_tools"] and item["action_servable"]:
                    failures.append(f"{unit_id}:action_servable_without_tools")
                # merge multi-tool proposals into one ANY_OF candidate when all validate
                if outcomes:
                    tools = tuple(dict.fromkeys(tool for outcome in outcomes for tool in outcome.serving_tools))
                    checks = tuple(dict.fromkeys(check for outcome in outcomes for check in outcome.argument_checks))
                    merged = OutcomeBinding(unit_id, tools, BindingLevel.ATTEMPT,
                                             tuple(checks), bool(item["action_servable"]), quotes)
                    outcome_pairs.append((unit_id, (merged,)))
                    stats["outcome_candidates_kept"] += 1
                else:
                    unbound.append(unit_id)
                continue
            candidates = []
            for binding in item["bindings"]:
                tool = binding["tool"]
                if tool not in self.tool_catalog:
                    failures.append(f"{unit_id}:tool_not_in_catalog")
                    stats["candidates_rejected"] += 1
                    continue
                level = BindingLevel(binding["level"])
                checks = self._checks([binding], tool, quotes, normative_texts, failures, unit_id)
                observation = None
                if binding["observation"] is not None:
                    observation = self._observation(binding["observation"], unit_id, failures)
                if unit_kind in {"STATE", "ACTOR"} and observation is None and unit_kind == "STATE":
                    failures.append(f"{unit_id}:state_without_observation")
                    stats["candidates_rejected"] += 1
                    continue
                candidate = AtomBindingCandidate(unit_id, tool, level, tuple(checks),
                                                 observation,
                                                 binding["observation"]["tool"] if binding["observation"] else None,
                                                 "assistant" if unit_kind == "ACTOR" else None,
                                                 tuple(binding.get("entity_path", ())), quotes)
                candidates.append(candidate)
                stats["candidates_kept"] += 1
            if candidates:
                atom_pairs.append((unit_id, tuple(candidates)))
            else:
                unbound.append(unit_id)
        record = BindingRecord(tuple(atom_pairs), tuple(outcome_pairs), tuple(unbound),
                               tuple(dict.fromkeys(failures)))
        return record, stats

    def _checks(self, bindings, tool, quotes, normative_texts, failures, unit_id):
        checks = []
        schema = self.schemas.get(tool, {})
        for binding in bindings if isinstance(bindings, list) else [bindings]:
            if not isinstance(binding, dict) or binding.get("tool") != tool:
                continue
            for check in binding.get("argument_checks", ()):
                path = tuple(check["path"])
                if not self._path_ok(schema, path, tool):
                    failures.append(f"{unit_id}:path_not_in_schema_or_call")
                    continue
                allowed, presence = [], bool(check["presence_only"])
                for encoded in check["allowed_json"]:
                    value, ok = _decode_literal(encoded)
                    if not ok:
                        failures.append(f"{unit_id}:noncanonical_literal")
                        continue
                    if not presence and not _literal_in_quote(value, quotes + tuple(normative_texts.values())):
                        failures.append(f"{unit_id}:literal_not_grounded")
                        continue
                    allowed.append(encoded)
                if not allowed:
                    continue
                quote = check.get("quote", "")
                if quote and not any(quote in text for text in normative_texts.values()) \
                        and not any(quote == q for q in quotes):
                    failures.append(f"{unit_id}:check_quote_not_found")
                    continue
                checks.append(BindingCheck(path, tuple(dict.fromkeys(allowed)), presence, quote))
        return tuple(dict.fromkeys(checks))

    def _path_ok(self, schema: dict, path: tuple[str, ...], tool: str) -> bool:
        if _path_exists_in_schema(schema, path):
            return True
        payloads = self.trajectory_payloads.get(tool, [])
        call_paths = set()
        for payload in self.schemas.get("__calls__", {}).get(tool, []):
            call_paths |= _payload_paths(payload)
        result_paths = set()
        for payload in payloads:
            result_paths |= _payload_paths(payload)
        return path in call_paths or path in result_paths

    def _observation(self, observation: dict, unit_id: str, failures: list):
        tool = observation["tool"]
        if tool not in self.tool_catalog:
            failures.append(f"{unit_id}:observation_tool_not_in_catalog")
            return None
        path = tuple(observation["path"])
        result_paths = set()
        for payload in self.trajectory_payloads.get(tool, []):
            result_paths |= _payload_paths(payload)
        if path not in result_paths:
            failures.append(f"{unit_id}:observation_path_not_in_trajectory")
            return None
        value, ok = _decode_literal(observation["expected_json"])
        if not ok:
            failures.append(f"{unit_id}:observation_noncanonical_literal")
            return None
        from .goal_types_v1 import ObservationBinding
        return ObservationBinding(tool, path, observation["expected_json"],
                                  tuple(observation.get("entity_path", ())))


def build_binding_payload(units: list[dict], tool_catalog, schemas, trajectory) -> dict:
    return {"semantic_units": units, "tool_catalog": [
        {"name": name, "arguments": schemas.get(name, {})} for name in tool_catalog],
        "trajectory": trajectory}


def run_semantic_binding(units: list[dict], tool_catalog, schemas: dict,
                         trajectory: list[dict], normative_texts: dict[str, str],
                         backend: SemanticBackend) -> tuple[BindingRecord, dict]:
    """One primary binding pass + one machine-validation repair re-ask."""
    payload = build_binding_payload(units, tool_catalog, schemas, trajectory)
    validator = SemanticBindingFrontend(tool_catalog, schemas,
                                        _trajectory_result_payloads(trajectory))
    call_payloads = {tool: [call.get("arguments") for call in trajectory
                            if call.get("event") == "call" and call.get("tool") == tool]
                     for tool in tool_catalog}
    validator.schemas = dict(schemas)
    validator.schemas["__calls__"] = call_payloads
    proposal = backend.propose(BINDING_TASK, payload, BINDING_SCHEMA)
    telemetry = {"transport_status": proposal.transport_status,
                 "schema_status": proposal.schema_status, "repair_used": False}
    value = proposal.value if proposal.transport_status == "SUCCESS" and proposal.schema_status == "VALID" else None
    if value is None:
        repair_payload = dict(payload)
        repair_payload["failed_attempt"] = {"transport_status": proposal.transport_status,
                                            "schema_status": proposal.schema_status,
                                            "payload_json": proposal.payload_json}
        repair_payload["machine_error"] = ("transport_error" if proposal.transport_status != "SUCCESS"
                                           else "schema_invalid")
        proposal = backend.propose(REPAIR_TASK, repair_payload, BINDING_SCHEMA)
        telemetry.update(repair_used=True, repair_transport_status=proposal.transport_status,
                         repair_schema_status=proposal.schema_status)
        value = proposal.value if proposal.transport_status == "SUCCESS" and proposal.schema_status == "VALID" else None
    if value is None:
        return BindingRecord((), (), tuple(unit["unit_id"] for unit in units),
                             ("TRANSPORT_OR_SCHEMA_FAILURE",)), telemetry
    record, stats = validator.validate(value, normative_texts)
    telemetry.update(stats)
    return record, telemetry


def _trajectory_result_payloads(trajectory: list[dict]) -> dict[str, list]:
    payloads = {}
    for event in trajectory:
        if event.get("event") == "result":
            payloads.setdefault(event.get("tool", ""), []).append(event.get("payload"))
    return payloads

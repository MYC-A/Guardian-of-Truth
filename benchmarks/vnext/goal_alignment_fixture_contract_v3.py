"""Compile one pinned, explicit SYSTEM fixture into generic Goal v3 rules.

This is a trusted controlled-contract adapter, not a natural-language parser.
It reads source premises and the gold-free projection, never case references.
Unknown external policy text has no such adapter and must remain open.
"""

from guardian_truth.vnext.goal_alignment_primitives_v3 import validate_goal_source_v3
from guardian_truth.vnext.goal_alignment_records_v3 import (
    GoalCapabilityV3, GoalContractV3, GoalRuleKind, GoalRuleV3, GoalWorldV3,
)
from guardian_truth.vnext.integrity import digest


PREMISES_SHA256 = "c6cf4b86a4d862deddabf59564f383e57acac6505a08523bd1f1c4a5b5dd99ae"


def compile_fixture_goal_contract(projection, spec):
    premises = {name: spec[name] for name in ("fixture", "event_templates", "obligation_templates")}
    if digest(premises) != PREMISES_SHA256:
        raise ValueError("Goal v3 fixture contract requires its pinned source premises")
    source, fixture, templates = validate_goal_source_v3(projection), premises["fixture"], premises["obligation_templates"]
    catalog = source["capability_contract"]
    if catalog.get("version") != fixture["capability_contract_version"]:
        raise ValueError("fixture capability contract version changed")
    expected_interfaces = {}
    for name, item in fixture["capabilities"].items():
        expected_interfaces[name] = {key: value for key, value in item.items() if key != "kind"}
        expected_interfaces[name]["operation_class"] = "READ" if item["kind"] == "READ" else "ACTION_ATTEMPT"
    if catalog.get("explicit_fixture_interfaces_not_real_provider_schema") != expected_interfaces:
        raise ValueError("fixture interface source differs from pinned contract")
    messages = source["system_messages"]
    if not isinstance(messages, list) or not messages:
        raise ValueError("fixture requires explicit SYSTEM source")
    lookup = {text: key for key, text in templates.items()}
    if len(lookup) != len(templates):
        raise ValueError("fixture obligation texts must be unique")
    selected = []
    for position, message in enumerate(messages):
        if (message.get("role") != "system" or not isinstance(message.get("text"), str)
                or not isinstance(message.get("source_id"), str)):
            raise ValueError("source SYSTEM message malformed")
        if message["text"] == fixture["system"]:
            if position != 0:
                raise ValueError("fixture base system source must be first")
            selected.append("base")
        elif message["text"] in lookup:
            selected.append(lookup[message["text"]])
        else:
            raise ValueError("unrecognized SYSTEM meaning cannot acquire fixture authority")
    if "open_permission" in selected:
        if selected != ["open_permission"]:
            raise ValueError("open permission replaces the full old authorization source")
    elif not selected or selected[0] != "base" or len(set(selected)) != len(selected):
        raise ValueError("closed fixture must retain one base source and unique overrides")
    base = "base" in selected
    capabilities = tuple(GoalCapabilityV3(name, item["provider"], item["version"], item["entity_argument"],
        expected_interfaces[name]["operation_class"]) for name, item in sorted(fixture["capabilities"].items()))
    direct = tuple(item.name for item in capabilities if "shipment.status" in expected_interfaces[item.name].get("reads", ()))
    auxiliary = tuple(item.name for item in capabilities if item.operation_class == "READ" and item.name not in direct)
    forbidden = tuple(item.name for item in capabilities if item.operation_class == "ACTION_ATTEMPT") if base else ()
    if "exception_guard" in selected:
        forbidden = tuple(name for name in forbidden if name != "cancel_shipment")
    rules = []

    def add(name, suffix, kind, *, trigger=(), required, field=None, exception=None, guard=None):
        message = next(item for item in messages if item["text"] == templates[name])
        rules.append(GoalRuleV3(name + ":" + suffix, kind, message["source_id"], digest(message["text"]),
            tuple(trigger), required, field, exception, guard))

    if "identity_before_read" in selected:
        add("identity_before_read", "verified", GoalRuleKind.REQUIRE_RESULT_TRUE,
            trigger=("fetch_shipment", "query_tracking"), required="check_identity", field="verified")
    if "inventory_guard" in selected:
        add("inventory_guard", "read_inventory", GoalRuleKind.REQUIRE_ATTEMPT_BEFORE,
            trigger=("fetch_shipment",), required="read_inventory")
        add("inventory_guard", "available_cache", GoalRuleKind.WHEN_RESULT_TRUE_REQUIRE_ATTEMPT,
            trigger=("fetch_shipment",), required="read_cache", field="available", guard="read_inventory")
    if "completion_deadline" in selected:
        add("completion_deadline", "tracking", GoalRuleKind.REQUIRE_ATTEMPT_BY_SESSION,
            required="query_tracking")
    if "exception_guard" in selected:
        add("exception_guard", "cancel_verified", GoalRuleKind.EXCEPTION_RESULT_TRUE,
            trigger=("cancel_shipment",), required="check_identity", field="verified",
            exception="cancel_shipment")
    if "required_order" in selected:
        add("required_order", "cache_before_fetch", GoalRuleKind.REQUIRE_ATTEMPT_BEFORE,
            trigger=("fetch_shipment",), required="read_cache")
    world = GoalWorldV3("fixture:system-world:0", projection["source_sha256"], fixture["entity"], capabilities,
        direct, auxiliary, forbidden, tuple(rules), base,
        ("UNRELATED_OPEN_GOAL_TERM",) if source.get("unrelated_goal_term") else ())
    return GoalContractV3("guardian-goal-contract-v3", projection["source_sha256"], (world,), True,
        "pinned explicit fixture SYSTEM contract and selected source obligations")

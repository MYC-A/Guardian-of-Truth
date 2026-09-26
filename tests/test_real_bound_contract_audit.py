"""Real public46 source checks for the narrow reviewed effect contracts."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pandas as pd

from experiments.searh_23.real_bound_contract_audit import audit, reviewed_contract
from guardian_truth.parsing import parse_catalog, parse_events
from guardian_truth.vnext.bound_tool_effects_v2 import BoundRegistry, evaluate_bound_t1
from guardian_truth.vnext.integrity import canonical
from guardian_truth.vnext.normalize import normalize, tool_identity
from guardian_truth.vnext.types import EffectStatus


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "valid.parquet"
REGISTRY = ROOT / "contracts/tool_effects_v1.json"


def real_pair(case_id, tool):
    row = next(row for row in pd.read_parquet(DATASET).itertuples() if row.id == case_id)
    catalog = parse_catalog(parse_events(row.prompt, "prompt"), row.prompt)
    original = next(item for item in json.loads(REGISTRY.read_text(encoding="utf-8"))["contracts"]
                    if item["tool"] == tool)
    raw = row.prompt[catalog.tools[tool].source.start:catalog.tools[tool].source.end]
    dataset_sha = hashlib.sha256(DATASET.read_bytes()).hexdigest()
    bound = reviewed_contract(tool, raw, dataset_sha, original)
    assert bound is not None
    identity = tool_identity(tool, {"exact_source_catalog": raw},
                             provider="guardian-public46", version=dataset_sha)
    events = normalize(row.prompt, row.response, tool_identities=(identity,))
    result = next(event for event in events if event.kind == "result" and event.tool == identity)
    call = next(event for event in events if event.kind == "call" and event.call_id == result.call_id)
    return bound, call, result


def test_real_source_coverage_is_three_precise_action_results_not_binary_accuracy():
    report = audit(DATASET, REGISTRY)
    assert report["total_confirmed_action_results"] == 3
    assert report["total_echo_rebound"] == 41
    assert (report["by_tool"]["get_order_details"]["paired_results"],
            report["by_tool"]["get_order_details"]["paired_after_echo"]) == (4, 14)
    assert (report["by_tool"]["get_reservation_details"]["paired_results"],
            report["by_tool"]["get_reservation_details"]["paired_after_echo"]) == (8, 39)
    # One accepted order result follows two malformed lookup attempts. A FIFO
    # pairing would attach it to the wrong call; the exact echoed ID selects
    # the later valid call.
    assert report["by_tool"]["get_order_details"]["echo_fifo_disagree_cases"] == [
        {"case_id": "retail__47::t12", "result_event_id": "e21"}]
    assert {name: value["confirmed"] for name, value in report["by_tool"].items()
            if value["confirmed"]} == {
        "cancel_reservation": 1, "exchange_delivered_order_items": 1, "resume_line": 1}
    # Same tool name in two domains has different source semantics.
    assert len(report["by_tool"]["get_user_details"]["catalog_sha256"]) == 2


def test_real_exchange_result_proves_request_only_and_wrong_entity_is_unknown():
    bound, call, result = real_pair("retail__29::t13", "exchange_delivered_order_items")
    registry = BoundRegistry((bound,))
    good = evaluate_bound_t1(registry, call, result)
    assert good.status is EffectStatus.TRUSTED_EFFECT
    assert [effect.predicate for effect in good.effects] == ["exchange_requested"]
    wrong_entity = replace(result, payload_json=canonical({**result.payload,
        "order_id": "#OTHER"}).decode())
    assert evaluate_bound_t1(registry, call, wrong_entity).effects == ()
    changed_status = replace(result, payload_json=canonical({**result.payload,
        "status": "completed"}).decode())
    assert evaluate_bound_t1(registry, call, changed_status).effects == ()


def test_real_contract_rejects_catalog_text_change_even_if_phrase_survives():
    bound, _, _ = real_pair("airline__7::t6", "cancel_reservation")
    source = "- cancel_reservation — Cancel the whole reservation. Also do something else."
    original = next(item for item in json.loads(REGISTRY.read_text(encoding="utf-8"))["contracts"]
                    if item["tool"] == "cancel_reservation")
    assert reviewed_contract("cancel_reservation", source, bound.t1.identity.version, original) is None

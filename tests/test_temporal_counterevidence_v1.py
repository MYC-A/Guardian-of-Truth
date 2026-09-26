"""Paired event controls for conservative temporal counterevidence."""

from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "searh_23"))

from temporal_counterevidence_v1 import _latest_positive, refute_broken


ROOT = Path(__file__).resolve().parents[1]


def frozen(suite, case_id):
    path = ROOT / "outputs" / "searh_23" / "call_condition_probe" / suite / "input.json"
    return next(item for item in json.loads(path.read_text(encoding="utf-8"))["inputs"]
                if item["id"] == case_id)


ADDRESS = ("Before dispatching any parcel, check that the address is valid "
           "for the SAME shipment.")
AUDIT = ("After a replacement completes successfully, record an audit for the SAME case. "
         "Do not record the completion audit before a successful replacement.")


def test_latest_positive_result_supersedes_earlier_negative_only_for_same_entity():
    good = frozen("parcel_v1", "parcel__dispatch_later_valid")
    assert refute_broken(good, ADDRESS).status == "REFUTED"
    for change in ({"valid": False}, {"shipment_id": "PK-9"}, {"valid": None}):
        bad = deepcopy(good)
        latest = bad["history"][-1]
        value = json.loads(latest["text"])
        value.update(change)
        latest["text"] = json.dumps(value)
        assert refute_broken(bad, ADDRESS).status == "UNRESOLVED"
    unpaired = deepcopy(good)
    extra = deepcopy(unpaired["history"][-1])
    extra["event_id"] += 1
    extra["text"] = json.dumps({"shipment_id": "PK-7", "valid": False})
    unpaired["history"].append(extra)
    assert refute_broken(unpaired, ADDRESS).status == "UNRESOLVED"


def test_prior_success_requires_matching_action_entity_and_paired_result():
    good = frozen("service_desk_v1_renamed", "renamed__desk_v1__call_ok_audit")
    assert refute_broken(good, AUDIT).event_ids == (12, 13)
    for mutation in ("wrong_entity", "failed", "wrong_action", "unpaired"):
        bad = deepcopy(good)
        call, result = bad["history"][-2:]
        if mutation == "wrong_entity":
            value = json.loads(result["text"])
            value["case_id"] = "CS-9999"
            result["text"] = json.dumps(value)
        elif mutation == "failed":
            value = json.loads(result["text"])
            value["status"] = "failed"
            result["text"] = json.dumps(value)
        elif mutation == "wrong_action":
            call["name"] = result["name"] = "log_completion"
        else:
            result["event_id"] += 2
        assert refute_broken(bad, AUDIT).status == "UNRESOLVED"


def test_one_positive_fact_cannot_refute_a_multi_condition_clause():
    item = frozen("service_desk_metamorphic_v1", "desk_meta__latest_stock_available")
    # The full clause contains identity, confirmation and authorization too.
    quote = item["policy"].split("- When stock is available", 1)[1].split("\n- ", 1)[0]
    quote = "When stock is available" + quote
    assert _latest_positive(item, quote).status == "UNRESOLVED"


def test_positive_result_does_not_refute_opposite_policy_polarity():
    item = frozen("parcel_v1", "parcel__dispatch_later_valid")
    prohibited = "Never dispatch a parcel when its address is valid."
    item["policy"] = prohibited
    assert refute_broken(item, prohibited).status == "UNRESOLVED"

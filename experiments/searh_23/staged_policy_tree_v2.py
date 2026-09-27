"""Post-hoc discriminator repair plus two new authored transfer policies.

V1 replies were reviewed before these prompts were written. Keep V1 frozen;
V2 is an exploratory ablation, never an independent benchmark score.
"""
from __future__ import annotations

import argparse
import json

import staged_policy_tree_v1 as v1
from policy_model_ab_v1 import sha


BASE = v1.ROOT / "experiments/searh_23/staged_policy_tree_v2"
OUT = v1.ROOT / "outputs/searh_23/staged_policy_tree_v2"

SCOPE_SYSTEM = """Read ONE source policy and a declared tool catalog.
Decide whether the clause is PRECONDITION or ORDERING, then locate the action
whose execution is restricted. Checks, lookups, authorizations and requests
are evidence or preparation, not the restricted business action.
PRECONDITION means a fact/check/approval must hold before one business action;
phrases 'before', 'after', 'only after', and 'requires' can express this.
ORDERING means two distinct business operations must be executed in a stated
sequence, such as cancellation then refund. The second operation is governed.
Return only JSON with exactly these keys:
{"kind":"PRECONDITION|ORDERING|UNSUPPORTED","governed_tool":"declared name or empty","prerequisite_tool":"declared name only for ORDERING, otherwise empty","action_quote":"unique exact continuous source substring naming the governed action"}.
Choose a longer source phrase if the short action word appears twice. Never
infer a tool not in the catalog. No case verdict or interpretation of results.
"""

BIND_SYSTEM = """Bind ONE exact cited prerequisite to the declared result
catalog. Return only one JSON object with exactly these keys:
{"evidence_tool":"declared name","join_key":"one exact shared ID field name","result_field":"declared Boolean result field","required_value":true,"temporal":"LATEST|PRIOR_TRUE"}.
join_key must be a STRING naming the target argument and result ID field,
not an object or a description. LATEST is only for explicit newest/latest/
current-state wording. A check that 'has returned' or 'was verified' means a
prior witness (PRIOR_TRUE) unless explicit revocation is stated. If the
condition cannot be represented using one declared Boolean result, return {}.
Do not evaluate a trace or invent a field.
"""

EXTRA_TASKS = [
    {"id": "parcel_handover_transfer", "split": "v2_new_authored",
     "query": {"policy": "A parcel may be handed over only after its barcode check has returned valid AND its latest custody check reports ready. Filing a handover request does not hand it over.",
               "tools": {
                   "check_barcode": {"description": "Read barcode validity for parcel; no handover.", "id": "parcel_id", "result": "valid"},
                   "check_custody": {"description": "Read current custody readiness; no handover.", "id": "parcel_id", "result": "ready"},
                   "file_handover_request": {"description": "Request later parcel handover; does not hand it over.", "id": "parcel_id", "result": "accepted"},
                   "handover_parcel": {"description": "Hand over the parcel now.", "id": "parcel_id", "result": "success"}},
               "target_argument_keys": ["parcel_id"]},
     "expected": {"kind": "PRECONDITION", "governed_tool": "handover_parcel",
                  "atoms": [{"evidence_tool": "check_barcode", "join_key": "parcel_id", "result_field": "valid", "required_value": True, "temporal": "PRIOR_TRUE"},
                            {"evidence_tool": "check_custody", "join_key": "parcel_id", "result_field": "ready", "required_value": True, "temporal": "LATEST"}]}},
    {"id": "vehicle_dispatch_transfer", "split": "v2_new_authored",
     "query": {"policy": "Before dispatching a vehicle, its latest safety inspection must report passed AND the assigned driver's license verification must have returned valid. Asking to dispatch does not dispatch the vehicle.",
               "tools": {
                   "inspect_safety": {"description": "Read current vehicle safety, no dispatch.", "id": "vehicle_id", "result": "passed"},
                   "verify_driver_license": {"description": "Verify assigned driver license, no dispatch.", "id": "driver_id", "result": "valid"},
                   "ask_to_dispatch": {"description": "Request later vehicle dispatch.", "id": "vehicle_id", "result": "accepted"},
                   "dispatch_vehicle": {"description": "Dispatch vehicle for the assigned driver now.", "id": "vehicle_id", "result": "success"}},
               "target_argument_keys": ["vehicle_id", "driver_id"]},
     "expected": {"kind": "PRECONDITION", "governed_tool": "dispatch_vehicle",
                  "atoms": [{"evidence_tool": "inspect_safety", "join_key": "vehicle_id", "result_field": "passed", "required_value": True, "temporal": "LATEST"},
                            {"evidence_tool": "verify_driver_license", "join_key": "driver_id", "result_field": "valid", "required_value": True, "temporal": "PRIOR_TRUE"}]}}
]


def _select_output() -> None:
    v1.BASE = BASE
    v1.OUT = OUT


def freeze() -> None:
    original = json.loads((v1.ROOT / "experiments/searh_23/staged_policy_tree_v1/frozen.json").read_text(encoding="utf-8"))
    original["systems"]["scope"] = SCOPE_SYSTEM
    original["systems"]["binding"] = BIND_SYSTEM
    original["tasks"].extend(EXTRA_TASKS)
    original["note"] = "v2 post-hoc prompt repair after v1; two new authored transfer clauses, no binary benchmark"
    BASE.mkdir(parents=True, exist_ok=True)
    path = BASE / "frozen.json"
    payload = json.dumps(original, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise ValueError("frozen v2 protocol changed")
    path.write_text(payload, encoding="utf-8")
    print(json.dumps({"tasks": len(original["tasks"]), "protocol_sha256": sha(original)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run", "score"))
    phase = parser.parse_args().phase
    _select_output()
    if phase == "freeze":
        freeze()
    elif phase == "run":
        v1.run()
    else:
        print(json.dumps(v1.score()))

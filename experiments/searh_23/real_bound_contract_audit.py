"""Read-only public46 coverage audit for three source-anchored tool effects.

This is a component replay over an already viewed dataset, not a Guardian
prediction. The three meanings below are reviewed against the exact public46
system catalog and the older DOC_EXPLICIT T1 registry. Other tools stay unknown.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import pandas as pd

from guardian_truth.parsing import parse_catalog, parse_events
from guardian_truth.vnext.bound_tool_effects_v2 import (
    BoundContract, BoundRegistry, FieldEquality, evaluate_bound_t1,
)
from guardian_truth.vnext.echo_pairing_v1 import ReadEchoContract, pair_read_echoes
from guardian_truth.vnext.integrity import canonical
from guardian_truth.vnext.normalize import normalize, tool_identity
from guardian_truth.vnext.tools import (
    ConditionalGuarantee, EffectSpec, FieldCondition, TrustedContract,
)
from guardian_truth.vnext.types import EffectStatus


# Exact postconditions; "exchange requested" does not certify an exchange
# completed, and a reader's returned status does not certify a mutation.
ACTION_SPECS = {
    "cancel_reservation": {
        "catalog_phrase": "Cancel the whole reservation.",
        "catalog_sha256": "5b9674b8cdb542e79b00f8bfb608b2073c912b5449a0e72c2dfd6691b2858da9",
        "argument_id": "reservation_id", "result_id": ("reservation_id",),
        "conditions": (("status", "cancelled"),),
        "effect": "reservation_cancelled", "value": True,
    },
    "exchange_delivered_order_items": {
        "catalog_phrase": "Exchange items in a delivered order to new items of the same product type.",
        "catalog_sha256": "e4e30a68a7a8c3b42b69a00ad6f2653bb66141c51b886c67b976e93458589c41",
        "argument_id": "order_id", "result_id": ("order_id",),
        "conditions": (("status", "exchange requested"),),
        "effect": "exchange_requested", "value": True,
    },
    "resume_line": {
        "catalog_phrase": "Logic: Sets line status to Active, clears suspension_start_date.",
        "catalog_sha256": "6a94c4428f6ff24f951e3b96e6bd3401e8ff32d28c3b208b373a03beb4e50250",
        "argument_id": "line_id", "result_id": ("line", "line_id"),
        "conditions": (("line.status", "Active"), ("line.suspension_start_date", None),
                       ("message", "Line resumed successfully")),
        "effect": "line_active", "value": True,
    },
}

READ_ECHO_SPECS = {
    "get_order_details": {
        "catalog_sha256": ("df847ab86410fd90901626e4e51fa404653fec9eabf2cb2d424b25da759695d0",),
        "argument": ("order_id",), "result": (("order_id",),),
    },
    "get_reservation_details": {
        "catalog_sha256": ("7a2eceada079d41667b662e29d28a4be0c0167365b81f3f93823a7ee96b41e78",),
        "argument": ("reservation_id",), "result": (("reservation_id",),),
    },
    "get_user_details": {
        "catalog_sha256": ("96156a008f8ae7826aff02cf60ccb645f0d125ee123941e0c4e5ab1dce1b538b",
                           "97c640a563c9ded6d60ad00b89963d4f5cc492f8cf81da1f232901b092587d8b"),
        "argument": ("user_id",), "result": (("user_id",),),
    },
}


def reviewed_contract(name: str, catalog_text: str, dataset_sha256: str, registry_row: dict):
    spec = ACTION_SPECS[name]
    if (spec["catalog_phrase"] not in catalog_text
            or hashlib.sha256(catalog_text.encode()).hexdigest() != spec["catalog_sha256"]):
        return None
    if registry_row["tool_version"] != "valid-" + dataset_sha256[:8]:
        return None
    if registry_row["tool"] != name or registry_row["evidence_source"] != "DOC_EXPLICIT":
        return None
    identity = tool_identity(name, {"exact_source_catalog": catalog_text},
                             provider="guardian-public46", version=dataset_sha256)
    conditions = tuple(FieldCondition("result", tuple(path.split(".")), canonical(value).decode())
                       for path, value in spec["conditions"])
    effect = EffectSpec(spec["argument_id"], spec["effect"],
                        canonical(spec["value"]).decode(), True)
    contract = TrustedContract(identity, (), tuple(registry_row["reads"]),
        tuple(registry_row["writes"]), (ConditionalGuarantee(conditions, (effect,)),),
        (), (), "failure gives no no-effect proof", "result event only", "unknown",
        "public46 system catalog + contracts/tool_effects_v1.json:" + name)
    return BoundContract(contract, (FieldEquality((spec["argument_id"],), spec["result_id"]),))


def audit(dataset: Path, registry_path: Path) -> dict:
    dataset_sha = hashlib.sha256(dataset.read_bytes()).hexdigest()
    original = json.loads(registry_path.read_text(encoding="utf-8"))
    rows_by_name = {row["tool"]: row for row in original["contracts"]}
    if len(rows_by_name) != len(original["contracts"]):
        raise ValueError("duplicate reviewed contract")
    summary = defaultdict(lambda: {"catalog_sha256": set(), "calls": 0, "results": 0,
                                   "paired_results": 0, "paired_after_echo": 0,
                                   "echo_rebound": 0, "echo_adjacent": 0,
                                   "echo_fifo_agree": 0, "echo_fifo_disagree_cases": [],
                                   "echo_nonadjacent_cases": [],
                                   "confirmed": 0, "confirmed_cases": []})
    recognized = Counter()
    for case in pd.read_parquet(dataset).itertuples():
        parsed = parse_events(case.prompt, "prompt")
        catalog = parse_catalog(parsed, case.prompt)
        if not catalog.complete:
            recognized["incomplete_catalog_cases"] += 1
            continue
        identities = []
        bound = []
        read_echoes = []
        for name, source_spec in catalog.tools.items():
            raw = case.prompt[source_spec.source.start:source_spec.source.end]
            identity = tool_identity(name, {"exact_source_catalog": raw},
                                     provider="guardian-public46", version=dataset_sha)
            identities.append(identity)
            if name in rows_by_name:
                entry = summary[name]
                entry["catalog_sha256"].add(hashlib.sha256(raw.encode()).hexdigest())
                if name in ACTION_SPECS:
                    candidate = reviewed_contract(name, raw, dataset_sha, rows_by_name[name])
                    if candidate is not None:
                        bound.append(candidate)
                    else:
                        recognized["rejected_action_contract_source"] += 1
                if name in READ_ECHO_SPECS:
                    read = READ_ECHO_SPECS[name]
                    if (hashlib.sha256(raw.encode()).hexdigest() in read["catalog_sha256"]
                            and rows_by_name[name]["evidence_source"] == "DOC_EXPLICIT"):
                        read_echoes.append(ReadEchoContract(identity, read["argument"],
                            read["result"], "public46 catalog + reviewed reader result echo:" + name))
        registry = BoundRegistry(tuple(bound))
        original_events = normalize(case.prompt, case.response, tool_identities=tuple(identities))
        pairing = pair_read_echoes(original_events, tuple(read_echoes))
        events = pairing.events
        original_by_id = {event.event_id: event for event in original_events}
        calls = {event.call_id: event for event in events if event.kind == "call"}
        call_order = defaultdict(list)
        result_ordinals = Counter()
        for item in events:
            if item.kind == "call" and item.tool:
                call_order[item.tool].append(item.call_id)
        for event in events:
            if not event.tool or event.tool.name not in rows_by_name:
                continue
            entry = summary[event.tool.name]
            if event.kind == "call":
                entry["calls"] += 1
            elif event.kind == "result":
                entry["results"] += 1
                ordinal = result_ordinals[event.tool]
                result_ordinals[event.tool] += 1
                if event.call_id and not event.pairing_issue:
                    entry["paired_after_echo"] += 1
                if event.event_id in pairing.rebound_result_ids:
                    entry["echo_rebound"] += 1
                    fifo_call = (call_order[event.tool][ordinal]
                                 if ordinal < len(call_order[event.tool]) else None)
                    if event.call_id == fifo_call:
                        entry["echo_fifo_agree"] += 1
                    else:
                        entry["echo_fifo_disagree_cases"].append({"case_id": case.id,
                            "result_event_id": event.event_id})
                    matched_call = calls.get(event.call_id)
                    if matched_call and event.index == matched_call.index + 1:
                        entry["echo_adjacent"] += 1
                    else:
                        entry["echo_nonadjacent_cases"].append({"case_id": case.id,
                            "result_event_id": event.event_id,
                            "gap": event.index - matched_call.index if matched_call else None})
                original_event = original_by_id[event.event_id]
                if original_event.call_id and not original_event.pairing_issue:
                    entry["paired_results"] += 1
                call = calls.get(event.call_id)
                if call is None or event.pairing_issue:
                    continue
                if event.tool.name in ACTION_SPECS:
                    decision = evaluate_bound_t1(registry, call, event)
                    if decision.status is EffectStatus.TRUSTED_EFFECT and decision.effects:
                        entry["confirmed"] += 1
                        entry["confirmed_cases"].append({"case_id": case.id,
                            "label": int(case.label), "call_event_id": call.event_id,
                            "result_event_id": event.event_id,
                            "bound_contract_sha256": registry.by_identity[call.tool].sha256,
                            "effect": decision.effects[0].predicate})
    return {"schema_version": "guardian-real-bound-audit-v1",
            "input_sha256": dataset_sha,
            "legacy_registry_sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
            "scope": "public46 inspected component coverage; no competition verdict changes",
            "recognized": dict(recognized),
            "by_tool": {name: {**entry, "catalog_sha256": sorted(entry["catalog_sha256"])}
                        for name, entry in sorted(summary.items())},
            "total_confirmed_action_results": sum(entry["confirmed"] for entry in summary.values()),
            "total_echo_rebound": sum(entry["echo_rebound"] for entry in summary.values())}


def main():
    root = Path(__file__).resolve().parents[2]
    result = audit(root / "valid.parquet", root / "contracts/tool_effects_v1.json")
    path = root / "outputs/searh_23/real_bound_contract_audit_v1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"confirmed": result["total_confirmed_action_results"],
        "by_tool": {name: {key: value for key, value in row.items()
                            if key not in {"confirmed_cases", "echo_nonadjacent_cases",
                                           "echo_fifo_disagree_cases"}}
                    for name, row in result["by_tool"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()

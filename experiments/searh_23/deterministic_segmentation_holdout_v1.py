"""Freeze additional original policy clauses and source cut positions.

This holdout is selected after seeing the earlier segmenter failures, but
before running the deterministic splitter against these clauses. Expected
positions are source offsets, never supplied to the splitter.
"""
from __future__ import annotations

import argparse
import json

from build_policy_atoms_v1 import ROOT
from call_condition_probe import input_record, load_cases
from policy_model_ab_v1 import sha
from source_scope_probe_v2 import bullets


BASE = ROOT / "experiments/searh_23/deterministic_segmentation_holdout_v1"
SOURCE_SCOPE = ROOT / "experiments/searh_23/source_scope_probe_v2/frozen.json"

PUBLIC_CLAUSES = {
    "airline": {44: ["changing cabin for just one"], 45: [], 46: [],
                51: ["The payment method must"], 59: [], 60: []},
    "banking": {0: ["IMPORTANT: Do not unlock"],
                5: ["Just explaining isn't enough", "you must use the"],
                6: ["and do not unlock tools"]},
    "telecom": {55: ["They should:"], 58: []},
}
PRIOR_CLAUSES = {
    "service_identity": ["Asking for confirmation"],
    "service_authorization": ["An authorization for another"],
    "hotel_identity": [],
}


def freeze() -> None:
    domains = {}
    for row in load_cases(ROOT / "outputs/full21/input/public46_label_free.csv"):
        domain = row["id"].split("_")[0]
        if domain in PUBLIC_CLAUSES and domain not in domains:
            source = input_record(row)
            if source:
                domains[domain] = source
    if set(domains) != set(PUBLIC_CLAUSES):
        raise ValueError("missing original public source")
    prior = json.loads(SOURCE_SCOPE.read_text(encoding="utf-8"))
    prior_by_id = {item["id"]: item["query"]["clause"] for item in prior["tasks"]}
    tasks = []
    for domain, selections in PUBLIC_CLAUSES.items():
        clauses = bullets(domains[domain]["policy"])
        for index, hints in selections.items():
            tasks.append({"id": f"{domain}_{index}", "source": "original_public46_system_policy",
                          "policy": clauses[index], "hints": hints})
    for ident, hints in PRIOR_CLAUSES.items():
        tasks.append({"id": ident, "source": "original_service_hotel_policy",
                      "policy": prior_by_id[ident], "hints": hints})
    for task in tasks:
        policy = task["policy"]
        offsets = []
        for hint in task.pop("hints"):
            if policy.count(hint) != 1:
                raise ValueError("gold cut hint missing/ambiguous: " + task["id"])
            offsets.append(policy.index(hint))
        task["expected_cut_offsets"] = sorted(offsets)
    protocol = {"tasks": tasks, "note": "post-hoc selected source; expected cuts frozen before deterministic run"}
    BASE.mkdir(parents=True, exist_ok=True)
    path = BASE / "frozen.json"
    payload = json.dumps(protocol, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise ValueError("frozen holdout changed")
    path.write_text(payload, encoding="utf-8")
    print(json.dumps({"tasks": len(tasks), "protocol_sha256": sha(protocol)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze",))
    parser.parse_args()
    freeze()

"""Freeze further original public policy clauses before deterministic replay.

Selected after the splitter was implemented and its first 14 cases scored.
Top-level source assertions are annotated; nested consequents sharing an IF
antecedent stay within one parent clause, as do illustrative examples.
"""
from __future__ import annotations

import argparse
import json

from build_policy_atoms_v1 import ROOT
from call_condition_probe import input_record, load_cases
from policy_model_ab_v1 import sha
from source_scope_probe_v2 import bullets


BASE = ROOT / "experiments/searh_23/deterministic_segmentation_transfer_v1"
SELECTED = {
    "airline": {11: [], 12: [], 25: [], 27: [], 35: [], 37: [], 39: [],
                40: ["but their prices"], 43: []},
    "banking": {1: ["Do not invent"], 7: ["Do not invent"]},
    "retail": {4: []},
    "telecom": {54: ["- This will change"]},
}


def freeze() -> None:
    sources = {}
    for row in load_cases(ROOT / "outputs/full21/input/public46_label_free.csv"):
        domain = row["id"].split("_")[0]
        if domain in SELECTED and domain not in sources:
            source = input_record(row)
            if source:
                sources[domain] = source
    if set(sources) != set(SELECTED):
        raise ValueError("missing original source domain")
    tasks = []
    for domain, selection in SELECTED.items():
        clauses = bullets(sources[domain]["policy"])
        for index, hints in selection.items():
            policy = clauses[index]
            offsets = []
            for hint in hints:
                if policy.count(hint) != 1:
                    raise ValueError("ambiguous source cut hint: " + domain + str(index))
                offsets.append(policy.index(hint))
            tasks.append({"id": f"{domain}_{index}", "policy": policy,
                          "expected_cut_offsets": sorted(offsets)})
    protocol = {"tasks": tasks,
                "note": "post-implementation source transfer; top-level assertions only; expected offsets frozen before replay"}
    BASE.mkdir(parents=True, exist_ok=True)
    path = BASE / "frozen.json"
    payload = json.dumps(protocol, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise ValueError("frozen transfer changed")
    path.write_text(payload, encoding="utf-8")
    print(json.dumps({"tasks": len(tasks), "protocol_sha256": sha(protocol)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze",))
    parser.parse_args()
    freeze()

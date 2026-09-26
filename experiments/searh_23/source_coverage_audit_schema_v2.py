"""Post-hoc repair of v1's underdescribed target-action argument schema."""
from __future__ import annotations

import argparse
import json

import source_coverage_audit_v1 as prior
from build_policy_atoms_v1 import BASE as ATOM_BASE, ROOT
from policy_model_ab_v1 import sha


BASE = ROOT / "experiments/searh_23/source_coverage_audit_schema_v2"
OUT = ROOT / "outputs/searh_23/source_coverage_audit_schema_v2"


def freeze() -> None:
    original = json.loads((prior.BASE / "frozen.json").read_text(encoding="utf-8"))
    tasks = []
    for original_task in original["tasks"]:
        name = original_task["id"].split("__", 1)[0]
        data = json.loads((ATOM_BASE / (name + ".json")).read_text(encoding="utf-8"))
        task = json.loads(json.dumps(original_task))
        target = task["query"]["restricted_action"]
        keys = sorted(data["cases"][0]["target_arguments"])
        task["query"]["tools"][target]["arguments"] = keys
        tasks.append(task)
    protocol = {"system": prior.SYSTEM, "tasks": tasks, "max_tokens": 250,
                "note": "post-hoc v1 catalog repair; target argument names disclosed, no values/cases/labels"}
    BASE.mkdir(parents=True, exist_ok=True)
    path = BASE / "frozen.json"
    payload = json.dumps(protocol, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise ValueError("frozen protocol changed")
    path.write_text(payload, encoding="utf-8")
    print(json.dumps({"tasks": len(tasks), "protocol_sha256": sha(protocol)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run", "score"))
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
    else:
        prior.BASE = BASE
        prior.OUT = OUT
        if args.phase == "run":
            prior.run()
        else:
            print(json.dumps(prior.score()))

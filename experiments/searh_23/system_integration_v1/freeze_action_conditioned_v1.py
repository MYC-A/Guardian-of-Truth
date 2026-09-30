"""Freeze an action-conditioned policy acquisition probe before API calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.integration.contracts import acquire_documented
from guardian_truth.step2.trusted import producer_scope
from guardian_truth.step2.types import EffectStrength
from eval_step2_documented import as_case

OUT = HERE / "frozen" / "action_conditioned_v1"
TRAJ = HERE / "frozen" / "trajectories_v1"
REFUSAL = HERE / "frozen" / "refusal_v1"


def _flatten(node: dict):
    operator, body = next(iter(node.items()))
    if operator == "source":
        return _flatten(body["gate"])
    if operator == "atom":
        return [body["predicate"]], []
    if operator in {"all", "any"}:
        required, exceptions = [], []
        for child in body:
            r, e = _flatten(child)
            required.extend(r)
            exceptions.extend(e)
        return required, exceptions
    if operator == "unless":
        base, older = _flatten(body["base"])
        exception, newer = _flatten(body["exception"])
        if len(base) != 1 or len(exception) != 1:
            raise ValueError("fixture oracle not flat under exception")
        return base, older + newer + [{"when": exception[0], "waives": base[0]}]
    raise ValueError("fixture oracle operation unsupported")


def _record(row: dict, program: dict, split: str):
    case = as_case(row)
    observations = [b for b in acquire_documented(case).bindings
                    if b.strength is EffectStrength.OBSERVED]
    menu = {}
    for b in observations:
        tool = next(t for t in case.tools
                    if producer_scope(case, t.get("name")) == b.producer)
        menu[b.predicate] = {"predicate": b.predicate,
                             "tool_description": tool["description"],
                             "entity_type": b.entity_type,
                             "input_fields": sorted(tool["parameters"])}
    required, exceptions = _flatten(program["gate"])
    query = {"id": row["family"], "policy": row["system_policy"],
             "governed_action": {"tool": program["governed_tool"],
                                 "description": program["governed_description"],
                                 "input_fields": sorted(next(
                                     t["parameters"] for t in case.tools
                                     if t["name"] == program["governed_tool"]))},
             "condition_menu": sorted(menu.values(), key=lambda x: x["predicate"])}
    gold = {"id": row["family"], "required": sorted(set(required)),
            "combine": "ALL", "exceptions": sorted(exceptions, key=lambda x: x["when"]),
            "activation": program["when"], "temporal": "LATEST_PRIOR"}
    return query, gold


def _unique(split: str):
    rows = json.loads((TRAJ / f"{split}_inputs.json").read_text(encoding="utf-8"))
    reviewed = json.loads((HERE / "reviewed_policy_programs_dev.json").read_text(
        encoding="utf-8"))["programs"]
    seen = set()
    pairs = []
    if split == "dev":
        for row in rows:
            if row["system_policy"] in seen:
                continue
            seen.add(row["system_policy"])
            program = next(p for p in reviewed if p["policy"] == row["system_policy"])
            pairs.append(_record(row, program, split))
    refusal_rows = json.loads((REFUSAL / f"{split}_inputs.json").read_text(encoding="utf-8"))
    for row in refusal_rows:
        if row["system_policy"] in seen or not row["reviewed_policy_programs"]:
            continue
        seen.add(row["system_policy"])
        pairs.append(_record(row, row["reviewed_policy_programs"][0], split))
    return pairs


def _write(name: str, data):
    raw = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    path = OUT / name
    if path.exists() and path.read_bytes() != raw:
        raise RuntimeError(f"frozen file differs: {path}")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = {}
    counts = {}
    for split in ("dev", "sealed"):
        pairs = _unique(split)
        counts[split] = len(pairs)
        files[f"{split}_queries.json"] = _write(f"{split}_queries.json",
                                                 [q for q, _ in pairs])
        files[f"{split}_gold.json"] = _write(f"{split}_gold.json",
                                              [g for _, g in pairs])
    manifest = {"suite": "action_conditioned_policy_v1",
                "frozen_at": "2026-09-30", "counts": counts,
                "source": "full trajectory and refusal_v1 frozen inputs; reviewed oracle programs",
                "query_excludes_gold_program": True,
                "known_limit": "structured contract menu and short authored policies",
                "files": files}
    _write("manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()

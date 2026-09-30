"""Replay F6 RAWSAN node formation in both scope modes without inference."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
IE = HERE.parent / "event_ie_frontends_v1"
W1 = HERE.parent / "step1_working_v1"
F6 = HERE.parent / "llm_first_f6"


def module_for(flag: str):
    os.environ["W1_SCOPE_GUARD"] = flag
    spec = importlib.util.spec_from_file_location(f"w1_scope_{flag}", W1 / "w1_pipe3.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def identity(nodes: list[dict]) -> list[dict]:
    return [{k: n.get(k) for k in ("node_id", "members", "span", "start",
                                     "type", "member_spans")}
            for n in nodes]


def main() -> None:
    cases_path = IE / "frozen/level_f6_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    old_env = os.environ.get("W1_SCOPE_GUARD")
    try:
        base = module_for("0")
        guarded = module_for("1")
        rows = []
        for c in cases:
            cid = c["case_id"]
            archived = json.loads((F6 / "outputs/stack/f6_rawsan" / f"{cid}.json")
                                  .read_text(encoding="utf-8"))
            b = identity(base.build_nodes_v3("RAWA", c))
            g = identity(guarded.build_nodes_v3("RAWA", c))
            old = identity(archived["nodes"])
            rows.append({"case_id": cid, "baseline_matches_saved": b == old,
                         "guard_changed_nodes": b != g,
                         "baseline_nodes": len(b), "guard_nodes": len(g)})
    finally:
        if old_env is None:
            os.environ.pop("W1_SCOPE_GUARD", None)
        else:
            os.environ["W1_SCOPE_GUARD"] = old_env
    out = {"python_hash_seed": os.environ.get("PYTHONHASHSEED"),
           "f6_inputs_sha256_worktree": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
           "baseline_matches_saved_all": all(x["baseline_matches_saved"] for x in rows),
           "changed_cases": [x["case_id"] for x in rows if x["guard_changed_nodes"]],
           "rows": rows}
    path = HERE / "outputs/f6_node_scope_replay.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}))


if __name__ == "__main__":
    main()

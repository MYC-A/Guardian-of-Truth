"""Unchanged V2 scope prompt on seven previously viewed original public46 clauses.

This tests source-language fit, not an unseen benchmark or full policy IR.
"""
from __future__ import annotations

import argparse
import json

import staged_policy_tree_v1 as v1
from policy_model_ab_v1 import sha
from staged_policy_tree_v2 import SCOPE_SYSTEM


BASE = v1.ROOT / "experiments/searh_23/staged_policy_scope_public_v1"
OUT = v1.ROOT / "outputs/searh_23/staged_policy_scope_public_v1"
SOURCE = v1.ROOT / "experiments/searh_23/source_scope_public_v1/frozen.json"


def freeze() -> None:
    old = json.loads(SOURCE.read_text(encoding="utf-8"))
    tasks = [{"id": row["id"], "query": {"policy": row["query"]["clause"],
                                       "tools": row["query"]["tools"]},
              "expected_scope": row["expected_scope"]} for row in old["tasks"]]
    protocol = {"systems": {"scope": SCOPE_SYSTEM}, "tasks": tasks, "max_tokens": 350,
                "note": "same V2 prompt; original public46 clauses already viewed in earlier studies; scope only"}
    BASE.mkdir(parents=True, exist_ok=True)
    path = BASE / "frozen.json"
    payload = json.dumps(protocol, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise ValueError("frozen public scope protocol changed")
    path.write_text(payload, encoding="utf-8")
    print(json.dumps({"tasks": len(tasks), "protocol_sha256": sha(protocol)}))


def run() -> None:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    model = v1.Mistral()
    v1.OUT = OUT
    for task in protocol["tasks"]:
        v1._ask(model, protocol, task, "scope", task["query"], "__scope")


def score() -> dict:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    rows = []
    for task in protocol["tasks"]:
        path = OUT / (task["id"] + "__scope.json")
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["protocol_sha256"] != sha(protocol) or record["query_sha256"] != sha(task["query"]):
            raise ValueError("public scope source/prompt mismatch")
        answer, query = record["answer"], task["query"]
        governed = answer.get("governed_tool")
        quote = answer.get("action_quote")
        valid = (record["finish_reason"] == "stop" and governed in query["tools"]
                 and v1.unique_span(query["policy"], quote) is not None)
        rows.append({"id": task["id"], "expected_scope": task["expected_scope"],
                     "kind": answer.get("kind"), "governed_tool": governed,
                     "action_quote": quote, "valid_literal": valid,
                     "scope_exact": valid and [governed] == task["expected_scope"]})
    result = {"protocol_sha256": sha(protocol), "rows": rows,
              "scope_exact": sum(row["scope_exact"] for row in rows), "total": len(rows)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "score.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key: value for key, value in result.items() if key != "rows"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run", "score"))
    phase = parser.parse_args().phase
    if phase == "freeze":
        freeze()
    elif phase == "run":
        run()
    else:
        print(json.dumps(score()))

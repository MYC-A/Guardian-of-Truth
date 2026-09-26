"""One post-hoc, quote-only repair of invalid source-scope responses.

The repair is selected by a syntax check, never by gold scope. It may change
only the copied source span. A changed tool list or a nonliteral span abstains.
"""
from __future__ import annotations

import argparse
import json

from build_policy_atoms_v1 import ROOT
from policy_model_ab_v1 import sha
from tq_questions import Mistral


BASE = ROOT / "experiments/searh_23/source_scope_quote_repair_v1"
OUT = ROOT / "outputs/searh_23/source_scope_quote_repair_v1"
SOURCE = ROOT / "experiments/searh_23/source_scope_public_v1/frozen.json"
ORIGINAL = ROOT / "outputs/searh_23/source_scope_public_v1"
SYSTEM = ("Copy an EXACT CONTINUOUS substring of the supplied policy clause "
          "that names the action constrained by the clause. Preserve its "
          "spelling, inflection, and punctuation, including typos. Keep the "
          "given scope_tools list UNCHANGED. Return one JSON object only: "
          '{"scope_tools":["exact existing tool name"],"action_quote":"literal substring"}. '
          "Do not reassess tool scope or policy compliance.")


def freeze() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    tasks = []
    for item in source["tasks"]:
        old = json.loads((ORIGINAL / (item["id"] + ".json")).read_text(encoding="utf-8"))
        if old["protocol_sha256"] != sha(source) or old["query_sha256"] != sha(item["query"]):
            raise ValueError("original response/protocol mismatch")
        ans = old["answer"]
        scope, quote = ans.get("scope_tools"), ans.get("action_quote")
        if not isinstance(scope, list) or not all(isinstance(x, str) and x in item["query"]["tools"] for x in scope):
            continue
        if not isinstance(quote, str) or quote not in item["query"]["clause"]:
            tasks.append({"id": item["id"], "split": item["split"],
                          "query": {"clause": item["query"]["clause"],
                                    "scope_tools": scope, "invalid_quote": quote},
                          "original_response_sha256": sha(old)})
    protocol = {"system": SYSTEM, "tasks": tasks, "max_tokens": 150,
                "note": "post-hoc syntax repair; does not change original first-pass score"}
    BASE.mkdir(parents=True, exist_ok=True)
    path = BASE / "frozen.json"
    payload = json.dumps(protocol, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        raise ValueError("frozen protocol changed")
    path.write_text(payload, encoding="utf-8")
    print(json.dumps({"tasks": len(tasks), "protocol_sha256": sha(protocol)}))


def valid_repair(task: dict, answer: object) -> bool:
    return (isinstance(answer, dict) and set(answer) == {"scope_tools", "action_quote"}
            and answer["scope_tools"] == task["query"]["scope_tools"]
            and isinstance(answer["action_quote"], str)
            and bool(answer["action_quote"])
            and answer["action_quote"] in task["query"]["clause"])


def run() -> None:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    model = Mistral()
    OUT.mkdir(parents=True, exist_ok=True)
    for task in protocol["tasks"]:
        path = OUT / (task["id"] + ".json")
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8"))
            if old["protocol_sha256"] != sha(protocol) or old["requested_model"] != model.model:
                raise ValueError("existing repair uses different protocol/model")
            continue
        response = model.ask(SYSTEM, json.dumps(task["query"], ensure_ascii=False), max_tokens=150)
        record = {"id": task["id"], "protocol_sha256": sha(protocol),
                  "query_sha256": sha(task["query"]), "requested_model": model.model,
                  "answer": response["value"], "finish_reason": response["finish_reason"],
                  "usage": response["usage"]}
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"id": task["id"], "finish_reason": record["finish_reason"]}), flush=True)


def score() -> dict:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    rows = []
    for task in protocol["tasks"]:
        record = json.loads((OUT / (task["id"] + ".json")).read_text(encoding="utf-8"))
        if record["protocol_sha256"] != sha(protocol) or record["query_sha256"] != sha(task["query"]):
            raise ValueError("repair response/protocol mismatch")
        accepted = record["finish_reason"] == "stop" and valid_repair(task, record["answer"])
        rows.append({"id": task["id"], "accepted": accepted,
                     "answer": record["answer"], "requested_model": record["requested_model"]})
    result = {"protocol_sha256": sha(protocol), "accepted": sum(r["accepted"] for r in rows),
              "total": len(rows), "rows": rows}
    (OUT / "score.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {k: v for k, v in result.items() if k != "rows"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run", "score"))
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
    elif args.phase == "run":
        run()
    else:
        print(json.dumps(score()))

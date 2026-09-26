"""Pinned Small 4 arm over the already frozen policy model comparison tasks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import policy_model_ab_v1 as original


BASE = original.ROOT / "experiments/searh_23/policy_model_ab_small4_v1"
OUT = original.ROOT / "outputs/searh_23/policy_model_ab_small4_v1"
MODEL = "mistral-small-2603"


def freeze() -> None:
    source = original.BASE / "frozen.json"
    protocol = json.loads(source.read_text(encoding="utf-8"))
    protocol["models"] = {"small4": MODEL}
    protocol["source_protocol_sha256"] = original.sha(json.loads(source.read_text(encoding="utf-8")))
    BASE.mkdir(parents=True, exist_ok=True)
    destination = BASE / "frozen.json"
    payload = json.dumps(protocol, ensure_ascii=False, indent=2) + "\n"
    if destination.exists() and destination.read_text(encoding="utf-8") != payload:
        raise ValueError("frozen Small 4 protocol changed")
    destination.write_text(payload, encoding="utf-8")
    print(json.dumps({"tasks": len(protocol["tasks"]),
                      "protocol_sha256": original.sha(protocol), "model": MODEL}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run", "score"))
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
        return
    original.BASE = BASE
    original.OUT = OUT
    if args.phase == "run":
        original.run("small4")
    else:
        print(json.dumps(original.score("small4")))


if __name__ == "__main__":
    main()

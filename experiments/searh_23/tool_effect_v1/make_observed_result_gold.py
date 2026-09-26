"""Freeze observed-result support labels for the already frozen paired cases."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = {
    "supported": "SUPPORTED_BY_RESULT",
    "related_result": "NOT_SUPPORTED_BY_THIS_RESULT",
    "audit_result": "NOT_SUPPORTED_BY_THIS_RESULT",
    "failed_result": "NOT_SUPPORTED_BY_THIS_RESULT",
    "wrong_entity": "NOT_SUPPORTED_BY_THIS_RESULT",
    "no_result": "UNKNOWN",
}


def main() -> None:
    for suite in ("dev", "fresh"):
        ids = [json.loads(line)["id"] for line in
               (HERE / f"{suite}.jsonl").read_text(encoding="utf-8").splitlines()]
        gold = {cid: LABELS[cid.rsplit("__", 1)[1]] for cid in ids}
        (HERE / f"{suite}.observed_gold.json").write_text(
            json.dumps(gold, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

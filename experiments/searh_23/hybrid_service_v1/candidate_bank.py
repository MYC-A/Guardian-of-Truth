"""Gold-blind, identical doc/claim bank for native specialist checkers.

This is a narrow support question. A support score is *not* by itself a
Guardian error verdict; policy applicability and user impact remain separate.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from structural_v02 import parse_case_v02  # noqa: E402

DATA = HERE / "dataset" / "fresh_v1"
BANK = HERE / "dataset" / "specialist_bank_v1"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def candidate_for(case):
    ctx = parse_case_v02(case["id"], case["prompt"], case["response"])
    calls = ctx.target().tool_calls
    if len(calls) == 1 and not ctx.target().text.strip():
        call = calls[0]
        claim = (f"The assistant may now call {call.name} with "
                 f"arguments {call.args_raw} for this request.")
        kind = "policy_action_permission"
    elif not calls and ctx.target().text.strip():
        claim = ctx.target().text.strip()
        kind = "reported_fact_or_uncertainty"
    else:
        claim = case["response"]
        kind = "mixed_or_unparsed_target"
    return {"id": case["id"], "document": case["prompt"],
            "claim": claim, "claim_kind": kind,
            "target_quote": case["response"],
            "source_sha256": _sha((case["prompt"] + "\x00" +
                                   case["response"]).encode("utf-8"))}


def build():
    BANK.mkdir(parents=True, exist_ok=True)
    source_manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    splits = {}
    for split in ("dev", "sealed"):
        source = DATA / f"{split}_input.jsonl"
        if _sha(source.read_bytes()) != source_manifest["splits"][split]["input_sha256"]:
            raise ValueError("frozen source input hash mismatch")
        rows = []
        for line in source.read_text(encoding="utf-8").splitlines():
            case = json.loads(line)
            rows.append(candidate_for(case))
        encoded = ("".join(json.dumps(row, ensure_ascii=False,
                                      sort_keys=True) + "\n" for row in rows)
                   .encode("utf-8"))
        path = BANK / f"{split}.jsonl"
        path.write_bytes(encoded)
        splits[split] = {"n": len(rows), "sha256": _sha(encoded),
                         "source_input_sha256":
                         source_manifest["splits"][split]["input_sha256"],
                         "claim_kinds": {kind: sum(r["claim_kind"] == kind
                                                  for r in rows)
                                         for kind in sorted({r["claim_kind"]
                                                             for r in rows})}}
    manifest = {"schema": "specialist-bank/1", "splits": splits,
                "question": "Does the source support the target claim/action permission?",
                "warning": ("A binary support score is not the final Guardian "
                            "ERROR label; abstention and task-specific policy "
                            "logic require separate handling.")}
    (BANK / "manifest.json").write_text(json.dumps(
        manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))

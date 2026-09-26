"""Contrastive policy-bullet/tool-role probe with source coverage.

This measures role extraction only. It does not turn model roles into binary
Guardian verdicts or treat a model's source quote as semantic proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build_policy_language_v1 import POLICIES, ROOT
from micrograph_certificate_v1 import _bullets
from policy_compile_probe_v1 import frozen, digest
from tq_questions import Mistral


SYSTEM = """Classify EVERY original policy bullet against the DECLARED tools. Return one JSON OBJECT only; its first character must be { and it must have an entries key. Never return a top-level array:
{"entries":[{"source_id":0,"source_quote":"copy exact source bullet","governs":["tool_name"],"evidence":["tool_name"],"relation":"LATEST_BOOLEAN|PRIOR_SUCCESS|UNSUPPORTED_EVIDENCE|OTHER"}, ...]}.
Include one entry per bullet, original order, exact source quote. `governs` contains only the tool(s) whose CURRENT call performs the constrained action. A lookup, check, search or read tool that merely observes a prerequisite is not governed by a restriction on a later mutation. `evidence` contains only tools whose RESULTS can establish the prerequisite; a call alone is not enough. Use declared descriptions, not names, to distinguish observing from acting. `LATEST_BOOLEAN` is a prior fact whose newest same-entity result controls; `PRIOR_SUCCESS` is an earlier successful mutation required before the current call. Use `UNSUPPORTED_EVIDENCE` if the policy names a necessary prerequisite for which no declared tool result can establish it. A user confirmation is not a tool result. Do not invent tools or drop a source bullet. Do not produce a verdict or rewrite policy text."""


OUT = ROOT / "outputs/searh_23/policy_language_v1"
EXPECTED = ROOT / "experiments/searh_23/policy_scope_expected_v1.json"


def run(suite: str) -> dict:
    source = frozen(suite)
    output = OUT / suite / "scope_roles.json"
    if output.exists():
        raise ValueError("scope model result already exists")
    tools = {name: spec.splitlines()[0] for name, spec in
             source["data"]["inputs"][0]["tools"].items()}
    query = {"policy_bullets": [{"source_id": i, "source_quote": q}
                                for i, q in enumerate(source["bullets"])],
             "declared_tools": tools}
    try:
        result = Mistral().ask(SYSTEM, json.dumps(query, ensure_ascii=False), max_tokens=1300)
    except ValueError as exc:
        if str(exc) != "model returned non-object JSON":
            raise
        result = {"value": {}, "finish_reason": "non_object_json", "usage": {}}
    record = {"suite": suite, "input_sha256_lf": source["input_sha256_lf"],
              "system_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
              "answer": result["value"], "finish_reason": result["finish_reason"],
              "usage": result["usage"]}
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"suite": suite, "finish_reason": result["finish_reason"], "usage": result["usage"]}


def score(suite: str) -> dict:
    source = frozen(suite)
    output = OUT / suite / "scope_roles.json"
    record = json.loads(output.read_text(encoding="utf-8"))
    if (record["input_sha256_lf"] != source["input_sha256_lf"]
            or record["system_sha256"] != hashlib.sha256(SYSTEM.encode()).hexdigest()):
        raise ValueError("scope probe source/prompt changed")
    seal = {"suite": suite, "input_sha256_lf": source["input_sha256_lf"],
            "roles_sha256_lf": digest(output)}
    seal_path = OUT / suite / "scope_prediction_seal.json"
    payload = json.dumps(seal, indent=2) + "\n"
    if seal_path.exists() and seal_path.read_text(encoding="utf-8") != payload:
        raise ValueError("scope seal differs")
    seal_path.write_text(payload, encoding="utf-8")
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))[suite]
    entries = record["answer"].get("entries")
    rows = []
    complete = (record["finish_reason"] == "stop" and isinstance(entries, list)
                and len(entries) == len(source["bullets"]))
    if complete:
        tools = set(source["data"]["inputs"][0]["tools"])
        for i, (entry, gold) in enumerate(zip(entries, expected)):
            valid = (isinstance(entry, dict) and entry.get("source_id") == i
                     and entry.get("source_quote") == source["bullets"][i]
                     and isinstance(entry.get("governs"), list)
                     and isinstance(entry.get("evidence"), list)
                     and all(isinstance(name, str) for name in
                             entry["governs"] + entry["evidence"])
                     and set(entry["governs"] + entry["evidence"]) <= tools)
            fields = ("governs", "evidence", "relation")
            exact = valid and all(entry.get(field) == gold[field] for field in fields)
            rows.append({"source_id": i, "valid": valid, "exact": exact,
                         "expected": gold, "actual": entry})
    report = {"suite": suite, "scope": "authored policies; role extraction only",
              "seal": seal, "coverage": complete,
              "exact": sum(row["exact"] for row in rows), "total": len(expected),
              "rows": rows}
    (OUT / suite / "scope_score.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"suite": suite, "coverage": complete, "exact": report["exact"],
            "total": report["total"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("run", "score"))
    parser.add_argument("suite", choices=tuple(POLICIES))
    args = parser.parse_args()
    print(json.dumps(run(args.suite) if args.phase == "run" else score(args.suite), ensure_ascii=False))


if __name__ == "__main__":
    main()

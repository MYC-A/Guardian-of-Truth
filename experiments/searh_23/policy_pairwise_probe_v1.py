"""One policy bullet/tool pair per Mistral call; diagnostic, never a verdict."""

from __future__ import annotations

import argparse
import hashlib
import json

from build_policy_language_v1 import POLICIES
from policy_compile_probe_v1 import digest, frozen
from policy_scope_probe_v1 import EXPECTED, OUT
from tq_questions import Mistral


SYSTEM = """For ONE original policy clause and ONE declared tool, return one JSON object with exactly these keys: {"governs_current_call":true,"result_can_establish_prerequisite":false}. Use JSON booleans. `governs_current_call` is true only if this tool's CURRENT invocation performs the action whose timing/permission the clause constrains. Checking a prerequisite does not perform a later action. `result_can_establish_prerequisite` is true only if a RESULT from this tool can directly establish the condition that must hold before the constrained action. A request or check call alone proves nothing; use the declared effect, not the tool name. Both booleans may be false. Do not give a violation verdict or reinterpret the policy as a new rule."""


def cases(suite: str) -> list[dict]:
    source = frozen(suite)
    tools = {name: spec.splitlines()[0] for name, spec in
             source["data"]["inputs"][0]["tools"].items()}
    return [{"source_id": i, "source_quote": clause,
             "tool_name": name, "tool_description": description}
            for i, clause in enumerate(source["bullets"])
            for name, description in tools.items()]


def run(suite: str) -> dict:
    source = frozen(suite)
    path = OUT / suite / "pairwise_roles.json"
    if path.exists():
        raise ValueError("pairwise model result already exists")
    rows = []
    for case in cases(suite):
        response = Mistral().ask(SYSTEM, json.dumps(case, ensure_ascii=False), max_tokens=150)
        rows.append({"question": case, "answer": response["value"],
                     "finish_reason": response["finish_reason"], "usage": response["usage"]})
    result = {"suite": suite, "input_sha256_lf": source["input_sha256_lf"],
              "system_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
              "rows": rows}
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"suite": suite, "calls": len(rows)}


def score(suite: str) -> dict:
    source = frozen(suite)
    path = OUT / suite / "pairwise_roles.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    questions = cases(suite)
    if record["input_sha256_lf"] != source["input_sha256_lf"] or record["system_sha256"] != hashlib.sha256(SYSTEM.encode()).hexdigest():
        raise ValueError("pairwise source/prompt changed")
    if [row["question"] for row in record["rows"]] != questions:
        raise ValueError("pairwise questions changed")
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))[suite]
    rows = []
    for row in record["rows"]:
        question = row["question"]
        gold = expected[question["source_id"]]
        answer = row["answer"]
        valid = (row["finish_reason"] == "stop" and isinstance(answer, dict)
                 and type(answer.get("governs_current_call")) is bool
                 and type(answer.get("result_can_establish_prerequisite")) is bool)
        want_governs = question["tool_name"] in gold["governs"]
        want_evidence = question["tool_name"] in gold["evidence"]
        rows.append({"source_id": question["source_id"], "tool_name": question["tool_name"],
                     "valid": valid,
                     "governs_exact": valid and answer["governs_current_call"] == want_governs,
                     "evidence_exact": valid and answer["result_can_establish_prerequisite"] == want_evidence,
                     "expected": {"governs_current_call": want_governs,
                                  "result_can_establish_prerequisite": want_evidence},
                     "actual": answer})
    report = {"suite": suite, "scope": "authored role extraction only; post-hoc prompt",
              "seal": {"input_sha256_lf": source["input_sha256_lf"],
                       "roles_sha256_lf": digest(path)},
              "calls": len(rows), "valid": sum(r["valid"] for r in rows),
              "governs_exact": sum(r["governs_exact"] for r in rows),
              "evidence_exact": sum(r["evidence_exact"] for r in rows), "rows": rows}
    (OUT / suite / "pairwise_score.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {k: report[k] for k in ("suite", "calls", "valid", "governs_exact", "evidence_exact")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("run", "score"))
    parser.add_argument("suite", choices=tuple(POLICIES))
    args = parser.parse_args()
    print(json.dumps(run(args.suite) if args.phase == "run" else score(args.suite)))


if __name__ == "__main__":
    main()

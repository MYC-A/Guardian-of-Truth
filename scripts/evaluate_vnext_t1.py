"""Freeze then evaluate T1 only. T2 and real-world tool generalization NOT_RUN."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess

from guardian_truth.vnext.fixture_contracts import FIXTURE_SCHEMA, archive_fixture_contract
from guardian_truth.vnext.integrity import digest, file_digest, verify_files, write_new
from guardian_truth.vnext.normalize import normalize, tool_identity
from guardian_truth.vnext.tools import ContractRegistry, evaluate_t1
from guardian_truth.vnext.types import EffectStatus


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = ["src/guardian_truth/vnext/tools.py", "src/guardian_truth/vnext/types.py",
    "src/guardian_truth/vnext/normalize.py", "src/guardian_truth/vnext/fixture_contracts.py",
    "src/guardian_truth/vnext/integrity.py", "src/guardian_truth/vnext/semantic.py",
    "scripts/evaluate_vnext_t1.py", "benchmarks/vnext/tool_semantics_v1.json",
    "benchmarks/vnext/tool_reference_v1.py", "src/guardian_truth/parsing.py"]


def source_commit():
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()


def proposal(case: dict) -> dict:
    # Only input is used; gold is intentionally not a function argument.
    value = case["input"]
    identity = tool_identity(value["tool"], FIXTURE_SCHEMA if value["schema_identity"] == "exact" else {"changed": True},
                             provider=value["provider"], version=value["version"])
    prompt = '⟦ASSISTANT_TOOL_CALL name="fixture.archive" call_id="a"⟧\n' + json.dumps(value["arguments"])
    prompt += '\n⟦TOOL_RESULT name="fixture.archive" requestor="assistant" call_id="a"⟧\n' + json.dumps(value["result"])
    call, result = normalize(prompt, "", tool_identities=(identity,))
    registry = ContractRegistry(()) if value["contract_version"] is None else ContractRegistry((archive_fixture_contract(),))
    answer = evaluate_t1(registry, call, result, prior_state={"archived": value["prior_archived"]})
    return {"case_id": case["case_id"], "input_sha256": digest(value),
        "status": answer.status.value, "effects": [asdict(effect) for effect in answer.effects],
        "no_effect_proved": answer.no_effect_proved, "reasons": [reason.value for reason in answer.reasons],
        "contract_available": value["contract_version"] is not None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["freeze", "run"])
    args = parser.parse_args()
    output = ROOT / "outputs/vnext"
    freeze_path = output / "tool_t1_freeze_v1.json"
    if args.phase == "freeze":
        dirty = subprocess.run(["git", "-C", str(ROOT), "diff", "HEAD", "--", *SOURCE_FILES],
                                check=True, capture_output=True).stdout
        if dirty:
            raise ValueError("commit implementation before stage freeze")
        write_new(freeze_path, {"schema_version": "guardian-vnext-t1-stage-freeze-v1",
            "architecture_commit": source_commit(), "provider": None, "model": None,
            "contract_sha256": archive_fixture_contract().sha256,
            "source_sha256": {name: file_digest(ROOT / name) for name in SOURCE_FILES},
            "decision_rule": "exact status and archived value; missing trusted contracts NOT_APPLICABLE to T1",
            "scope": "controlled executable fixture only; no claim of real-world coverage or T2 gain"})
        print(json.dumps({"status": "T1_STAGE_FROZEN", "api_requests": 0}))
        return 0
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    failures = verify_files(ROOT, freeze["source_sha256"])
    if failures:
        raise ValueError("frozen T1 sources changed: " + str(failures))
    data = json.loads((ROOT / "benchmarks/vnext/tool_semantics_v1.json").read_text(encoding="utf-8"))
    predictions = [proposal({"case_id": case["case_id"], "input": case["input"]}) for case in data["cases"]]
    # Persist and hash proposals before joining development gold.
    predictions_path = output / "tool_t1_predictions_v1.json"
    write_new(predictions_path, {"prediction_sha256": digest(predictions), "rows": predictions})
    per_case = []
    correct = evaluated = no_effect_errors = false_causal = 0
    for case, actual in zip(data["cases"], predictions):
        if not actual["contract_available"]:
            per_case.append({"case_id": case["case_id"], "status": "NOT_APPLICABLE_T1",
                             "reason": "missing trusted contract; T2 is separate and NOT_RUN"})
            continue
        expected = case["gold"]
        evaluated += 1
        archived = json.loads(actual["effects"][0]["value_json"]) if actual["status"] == "TRUSTED_EFFECT" and actual["effects"] else None
        matches = actual["status"] == expected["effect_status"] and archived == expected["archived"]
        correct += matches
        no_effect_errors += actual["no_effect_proved"] and case["family"] != "no_op"
        false_causal += any(effect["causal_action_confirmed"] for effect in actual["effects"]) and case["family"] != "completed"
        per_case.append({"case_id": case["case_id"], "correct": matches,
            "actual_status": actual["status"], "expected_status": expected["effect_status"],
            "components": [] if matches else ["TOOL_EFFECT"]})
    report = {"schema_version": "guardian-vnext-t1-stage-results-v1", "status": "T1_COMPLETE_T2_NOT_RUN",
        "benchmark_role": "CONTROLLED_DEVELOPMENT_EXTENSION", "freeze_sha256": file_digest(freeze_path),
        "architecture_commit": freeze["architecture_commit"], "predictions_file_sha256": file_digest(predictions_path),
        "proposals_persisted_before_gold_join": True, "api_requests": 0, "T1": {
            "total_cases": len(predictions), "evaluated": evaluated, "correct": correct,
            "not_applicable_missing_contract": len(predictions) - evaluated,
            "exact_accuracy": correct / evaluated if evaluated else None,
            "false_no_effect": no_effect_errors, "false_causal_action_confirmation": false_causal},
        "T2": {"status": "NOT_RUN", "reason": "semantic model stage not frozen/run yet"},
        "per_case": per_case, "real_world_generalization": "NOT_ESTABLISHED", "downstream_gain": "NOT_ESTABLISHED"}
    write_new(output / "tool_t1_results_v1.json", report)
    print(json.dumps({"status": report["status"], "evaluated": evaluated, "correct": correct,
                      "not_applicable": len(predictions) - evaluated, "api_requests": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Three-phase, zero-LLM baseline of the existing pinned Goal v3 fixture kernel.

freeze separates source-only inputs from reference labels; predict reads only
the input/premises; score opens gold only after the complete prediction seal.
This is 36-case observed development, not the requested 60-case Goal-only test.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess

from benchmarks.vnext.goal_alignment_fixture_contract_v3 import compile_fixture_goal_contract
from benchmarks.vnext.goal_alignment_source_adapter_v1 import project_goal_alignment_source
from guardian_truth.vnext.goal_alignment_v3 import decide_goal_alignment_v3
from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, verify_files, write_new


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/vnext"
SPEC = ROOT / "benchmarks/vnext/goal_alignment_v3_mechanisms_v1.spec.json"
PREFIX = "goal_v3_fixture_offline_v1"
SOURCE_FILES = (
    "src/guardian_truth/vnext/goal_alignment_records_v3.py",
    "src/guardian_truth/vnext/goal_alignment_primitives_v3.py",
    "src/guardian_truth/vnext/goal_alignment_v3.py",
    "src/guardian_truth/vnext/goal_alignment_certificate_v3.py",
    "benchmarks/vnext/goal_alignment_fixture_contract_v3.py",
    "benchmarks/vnext/goal_alignment_source_adapter_v1.py",
    "scripts/evaluate_goal_v3_fixture_offline_v1.py",
)


def path(suffix):
    return OUT / f"{PREFIX}_{suffix}.json"


def read(suffix):
    return json.loads(path(suffix).read_text(encoding="utf-8"))


def freeze():
    if any(path(name).exists() for name in ("freeze", "inputs", "gold", "premises")):
        raise FileExistsError("fixture baseline freeze already exists")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *SOURCE_FILES], cwd=ROOT).returncode:
        raise ValueError("commit baseline runner and implementation before freeze")
    if any(subprocess.run(["git", "ls-files", "--error-unmatch", name], cwd=ROOT,
                          capture_output=True).returncode for name in SOURCE_FILES):
        raise ValueError("all candidate sources must be tracked")
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    premises = {name: spec[name] for name in ("fixture", "event_templates", "obligation_templates")}
    inputs = [{"case_id": case["id"], "projection": project_goal_alignment_source(spec, case)}
              for case in spec["cases"]]
    gold = {case["id"]: case["reference"] for case in spec["cases"]}
    if len(inputs) != 36 or len(gold) != 36:
        raise ValueError("expected 36 unique pinned development cases")
    write_new(path("inputs"), inputs)
    write_new(path("gold"), gold)
    write_new(path("premises"), premises)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
        capture_output=True, text=True, check=True).stdout.strip()
    write_new(path("freeze"), {"schema_version": "guardian-goal-v3-fixture-offline-freeze-v1",
        "scope": "OBSERVED_PINNED_FIXTURE_DIAGNOSTIC_NOT_GOAL_ONLY_60_CASE_EXPERIMENT",
        "architecture_commit": commit, "implementation_origin_commit": "48b84e3875b960d43956576735d543e8c4e5917b",
        "prompt_version": "NONE_OFFLINE", "schema_version_model": "NONE_OFFLINE",
        "provider": "NONE", "model": "NONE", "api_budget": 0,
        "case_ids": [row["case_id"] for row in inputs],
        "source_sha256": {name: file_digest(ROOT / name) for name in SOURCE_FILES},
        "spec_sha256": file_digest(SPEC), "inputs_sha256": file_digest(path("inputs")),
        "gold_sha256": file_digest(path("gold")), "premises_sha256": file_digest(path("premises")),
        "scoring": "exact source-owned status/alignment; all 36 cases; no semantic equivalence claim",
        "no_postresult_change_same_version": True})


def predict():
    frozen = read("freeze")
    if verify_files(ROOT, frozen["source_sha256"]) or file_digest(path("inputs")) != frozen["inputs_sha256"]:
        raise ValueError("frozen candidate/input hash mismatch")
    if file_digest(path("premises")) != frozen["premises_sha256"]:
        raise ValueError("source premises changed")
    inputs, premises = read("inputs"), read("premises")
    if [row["case_id"] for row in inputs] != frozen["case_ids"]:
        raise ValueError("case IDs changed")
    rows = []
    for row in inputs:
        projection = row["projection"]
        contract = compile_fixture_goal_contract(projection, premises)
        result = decide_goal_alignment_v3(projection, contract, fixture_spec=premises)
        rows.append({"case_id": row["case_id"], "source_sha256": projection["source_sha256"],
            "prediction": asdict(result), "api_requests": 0})
    write_new(path("predictions"), rows)
    write_new(path("prediction_seal"), prediction_seal(rows, frozen["case_ids"],
        architecture_commit=frozen["architecture_commit"], configuration_sha256=digest(frozen)))


def score():
    frozen, rows, seal = read("freeze"), read("predictions"), read("prediction_seal")
    if seal != prediction_seal(rows, frozen["case_ids"], architecture_commit=frozen["architecture_commit"],
                               configuration_sha256=digest(frozen)):
        raise ValueError("gold cannot be opened before complete exact prediction seal")
    if file_digest(path("gold")) != frozen["gold_sha256"]:
        raise ValueError("frozen gold bytes changed")
    gold = read("gold")
    if set(gold) != set(frozen["case_ids"]):
        raise ValueError("gold case inventory changed")
    cases = []
    for row in rows:
        expected, actual = gold[row["case_id"]], row["prediction"]
        cases.append({"case_id": row["case_id"], "expected_status": expected["status"],
            "actual_status": actual["status"], "status_correct": expected["status"] == actual["status"],
            "expected_alignment": expected.get("alignment"), "actual_alignment": actual["alignment"],
            "alignment_correct": expected.get("alignment") in (None, actual["alignment"]),
            "certificate_valid": actual["certificate_valid"]})
    write_new(path("results"), {"experiment": PREFIX, "scope": frozen["scope"],
        "architecture_commit": frozen["architecture_commit"], "prompt_version": frozen["prompt_version"],
        "schema_version_model": frozen["schema_version_model"], "case_count": len(cases),
        "status_correct": sum(item["status_correct"] for item in cases),
        "alignment_correct_when_annotated": sum(item["alignment_correct"] for item in cases if item["expected_alignment"]),
        "alignment_annotated": sum(bool(item["expected_alignment"]) for item in cases),
        "core_counts": {status: sum(item["actual_status"] == status for item in cases)
            for status in ("PROVED_ERROR", "PROVED_NO_ERROR", "UNRESOLVED", "INCONSISTENT")},
        "definitive_certificates_valid": sum(item["certificate_valid"] is True for item in cases),
        "api_requests": 0, "tokens": 0, "cost": "ZERO_OFFLINE",
        "freeze_sha256": file_digest(path("freeze")), "prediction_seal_sha256": file_digest(path("prediction_seal")),
        "cases": cases, "limitations": ["observed controlled SYSTEM fixture, not user-goal-only semantics",
            "not a general NL frontend, Policy/Core composition or new 60-case experiment"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "predict", "score"))
    phase = parser.parse_args().phase
    {"freeze": freeze, "predict": predict, "score": score}[phase]()
    print(json.dumps({"phase": phase, "status": "COMPLETE", "api_requests": 0}))


if __name__ == "__main__":
    main()

"""System boundary controls: later events and unreviewed scopes stay unresolved."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments/searh_23/system_integration_v1"))

from guardian_truth.integration.proof_engine import load_reviewed_programs
from guardian_truth.integration.system_runtime import analyze_system_case
from guardian_truth.step2.verifier import CallEvent
from eval_step2_documented import as_case

HERE = ROOT / "experiments/searh_23/system_integration_v1"


def _depot():
    rows = json.loads((HERE / "frozen/trajectories_v1/dev_inputs.json").read_text(
        encoding="utf-8"))
    row = next(x for x in rows if x["case_id"] == "depot.success")
    case = as_case(row)
    program = next(p for p in load_reviewed_programs(
        HERE / "reviewed_policy_programs_dev.json") if p.policy == case.category)
    raw = next(x["prediction"]["raw"] for x in json.loads(
        (HERE / "outputs/step3_candidate_dev.json").read_text(encoding="utf-8"))
        ["per_case"] if x["case_id"] == row["case_id"])
    return row, case, program, raw


def test_future_violation_cannot_retroactively_change_target_verdict():
    row, case, program, raw = _depot()
    response = row["target_response"]
    baseline = analyze_system_case(
        case, response=response["text"], response_index=response["index"],
        programs=(program,), reviewed_policy_scope_complete=True,
        candidate_claim_raw=raw, reviewed_non_refusal=True)
    assert baseline["status"] == "NO_ERROR"
    later = CallEvent(response["index"] + 1, "future-violation",
                      program.governed_tool, {"parcel_id": "P-99"})
    altered = replace(case, calls=case.calls + (later,))
    result = analyze_system_case(
        altered, response=response["text"], response_index=response["index"],
        programs=(program,), reviewed_policy_scope_complete=True,
        candidate_claim_raw=raw, reviewed_non_refusal=True)
    assert result["status"] == "NO_ERROR"
    assert all(p.get("target_call_id") != later.call_id
               for p in result["policy"]["action_proofs"])


def test_missing_reviewed_scope_or_refusal_review_cannot_grant_no_error():
    row, case, program, raw = _depot()
    response = row["target_response"]
    for programs, policy_complete, non_refusal in (
        ((), False, True),
        ((program,), False, True),
        ((program,), True, False),
    ):
        result = analyze_system_case(
            case, response=response["text"], response_index=response["index"],
            programs=programs,
            reviewed_policy_scope_complete=policy_complete,
            candidate_claim_raw=raw, reviewed_non_refusal=non_refusal)
        assert result["status"] == "UNKNOWN"

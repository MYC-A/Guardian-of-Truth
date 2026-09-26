"""Replay soundness counterexamples against an isolated generality branch checkout.

Usage: python experiments/searh_23/audit_generality_counterexamples.py
       --branch-root ../Guardian-of-Truth-generality-audit
No API/model calls and no source edits. Output is a diagnostic, not a score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


EXPECTED_COMMIT = "529b338"


def run(branch_root: Path) -> dict:
    branch_root = branch_root.resolve()
    commit = subprocess.check_output(["git", "-C", str(branch_root), "rev-parse", "HEAD"],
                                     text=True).strip()
    if not commit.startswith(EXPECTED_COMMIT):
        raise ValueError("counterexamples require the frozen generality branch commit")
    os.environ["GOT_ROOT"] = str(branch_root)
    sys.path.insert(0, str(branch_root / "experiments/generality26"))
    sys.path.insert(0, str(branch_root / "experiments/searh_23"))
    import common  # noqa: E402
    import probe_b2  # noqa: E402
    import probe_b3  # noqa: E402

    cases = []

    def record(name, actual, required):
        cases.append({"name": name, "actual": actual, "required_sound_value": required,
                      "unsound_positive": actual == "ESTABLISHES" or actual == "TRUE"})

    record("refund_success_used_as_replacement_proof",
           probe_b2.typing_verdict("refund_fee",
               {"status": "success", "success": True, "case_id": "SD-5101"},
               "The device replacement is completed."), "NEITHER")
    record("replacement_result_for_wrong_case",
           probe_b2.typing_verdict("execute_replacement",
               {"status": "success", "success": True, "case_id": "SD-9999"},
               "The device replacement is completed for SD-5101."), "NEITHER")

    prompt = ("\u27e6SYSTEM\u27e7\n[AVAILABLE TOOLS]\n"
              "- verify_requester \u2014 Compare requester identity with one case.\n"
              "    case_id: string! \u2014 Case ID.\n"
              "    name: string! \u2014 Requester name.\n"
              "\u27e6ASSISTANT\u27e7\n"
              "\u2192 TOOL_CALL verify_requester: {\"case_id\":\"A\",\"name\":\"Ana\"}\n"
              "\u2190 TOOL_RESPONSE verify_requester: {\"case_id\":\"B\",\"match\":true}\n")
    facts = common.extract_facts({"prompt": prompt,
        "response": "\u27e6ASSISTANT\u27e7\nReady."}, common.parse_catalog(prompt))
    check = probe_b3.check_condition_v3("IDENTITY_VERIFIED", {"case_id": "A"}, facts)[0]
    record("result_B_paired_with_call_A_as_verified_A", check, "UNKNOWN")

    facts = {"authorizations": [{"positive": True, "call_kv": {"case_id": "B"},
                                  "kv": {"authorization_status": "granted", "amount": 250},
                                  "amount": 250}],
             "effects": [{"success": True, "call_kv": {"case_id": "A"},
                          "tool": "refund_fee"}]}
    record("same_amount_wrong_case_accepted",
           probe_b3.check_condition_v3("AMOUNT_EXACT", {"case_id": "A", "amount": 250}, facts)[0],
           "UNKNOWN")
    record("refund_accepted_as_prior_replacement",
           probe_b3.check_condition_v3("PRIOR_SUCCESS", {"case_id": "A"}, facts)[0],
           "UNKNOWN")
    facts["authorizations"] = [{"positive": True, "call_kv": {"case_id": "A"},
                                "kv": {"authorization_status": "granted"}, "amount": None}]
    record("exact_amount_missing_but_accepted",
           probe_b3.check_condition_v3("AUTHORIZATION_EXACT", {"case_id": "A", "amount": 250}, facts)[0],
           "UNKNOWN")

    files = ("experiments/generality26/common.py", "experiments/generality26/probe_b2.py",
             "experiments/generality26/probe_b3.py")
    return {"schema_version": "generality-counterexamples-v1", "source_commit": commit,
            "source_sha256": {file: hashlib.sha256((branch_root / file).read_bytes()).hexdigest()
                              for file in files},
            "no_model_or_api_calls": True, "cases": cases,
            "unsound_positive_count": sum(item["unsound_positive"] for item in cases)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.branch_root)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"source_commit": result["source_commit"],
                      "unsound_positive_count": result["unsound_positive_count"],
                      "cases": result["cases"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

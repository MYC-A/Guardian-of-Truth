"""Offline counterexamples to overclaiming extraction/roundtrip guarantees.

These hand-authored propositional examples are method audits, not a benchmark
or model-quality measurement. No API calls, model imports or GPU use occur.
The optional external checker audit supplies mocked process output only.
"""
import argparse
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import subprocess
from unittest.mock import patch


def compare(name, variables, reference, candidate):
    counterexamples = []
    checked = 0
    for values in itertools.product((False, True), repeat=len(variables)):
        assignment = dict(zip(variables, values))
        expected, actual = bool(reference(assignment)), bool(candidate(assignment))
        checked += 1
        if expected != actual:
            counterexamples.append({**assignment, "reference_compliant": expected,
                                    "candidate_compliant": actual})
    return {"name": name, "assignments_checked": checked,
            "equivalent": not counterexamples, "counterexamples": counterexamples}


def run():
    correct_scope = lambda v: not v["execute"] or v["approval"]
    wrong_scope = lambda v: not v["lookup"] or v["approval"]
    scope_variables = ["execute", "lookup", "approval"]
    roundtrip = compare("stable_wrong_roundtrip", scope_variables, wrong_scope, wrong_scope)
    source = compare("roundtrip_vs_original_scope", scope_variables, correct_scope, wrong_scope)
    conjunction = compare("and_replaced_by_or", ["execute", "approval", "identity"],
        lambda v: not v["execute"] or (v["approval"] and v["identity"]),
        lambda v: not v["execute"] or (v["approval"] or v["identity"]))
    exception = compare("lost_exception", ["execute", "approval", "exception"],
        lambda v: not v["execute"] or v["approval"] or v["exception"],
        lambda v: not v["execute"] or v["approval"])
    binding = compare("lost_parent_or_time", ["execute", "approval", "same_parent", "prior"],
        lambda v: not v["execute"] or (v["approval"] and v["same_parent"] and v["prior"]),
        lambda v: not v["execute"] or v["approval"])
    reversed_implication = compare("necessary_replaced_by_sufficient", ["execute", "approval"],
        lambda v: not v["execute"] or v["approval"],
        lambda v: not v["approval"] or v["execute"])
    assert roundtrip["equivalent"] and not source["equivalent"]
    assert all(not item["equivalent"] for item in
               (conjunction, exception, binding, reversed_implication))
    text = "Parent A: Approval is recorded.\nParent B: Approval is recorded."
    quote = "Approval is recorded."
    positions = [i for i in range(len(text)) if text.startswith(quote, i)]
    assert len(positions) == 2
    return {"kind": "HAND_AUTHORED_METHOD_LIMITS_NOT_MODEL_BENCHMARK",
            "api_calls": 0, "solver_executed": False,
            "formula_semantics": "Boolean compliance under explicit hand-authored propositions",
            "roundtrip_consistency": roundtrip, "source_faithfulness": source,
            "other_semantic_errors": [conjunction, exception, binding, reversed_implication],
            "literal_quote_ambiguity": {"source": text, "quote": quote,
                                        "positions": positions, "unique": False}}


def audit_external_checker(path):
    """Inspect only the already-reviewed stdlib checker with a mocked process.

    This is a deterministic response-parser audit. Z3 is not installed or run.
    """
    spec = importlib.util.spec_from_file_location("reviewed_roundtrip_z3_checker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stdout = '(error "line 8 column 19: unknown constant unsatisfied")\nsat\n'
    process = subprocess.CompletedProcess(["z3", "mock.smt2"], 1, stdout, "")
    with patch.object(module.subprocess, "run", return_value=process):
        result = module.Z3Checker().check_equivalence("true", "false")
    return {"kind": "MOCKED_PROCESS_OUTPUT_NO_Z3_EXECUTION",
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "mock_returncode": process.returncode, "mock_stdout": stdout,
            "actual_checker_result": result,
            "finding": "Checker accepted UNSAT despite solver error, nonzero status and sat line",
            "parser_failure_reproduced": result["result"] == "UNSAT"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reviewed-checker", type=Path)
    args = parser.parse_args()
    result = run()
    if args.reviewed_checker:
        result["external_checker_response_audit"] = audit_external_checker(args.reviewed_checker)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"api_calls": 0, "roundtrip_passes_wrong_scope": True,
                      "semantic_counterexamples": sum(len(item["counterexamples"]) for item in
                          [result["source_faithfulness"], *result["other_semantic_errors"]]),
                      "external_checker_audited": bool(args.reviewed_checker)}))


if __name__ == "__main__":
    main()

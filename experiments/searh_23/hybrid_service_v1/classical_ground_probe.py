"""Fixed-IR backend diagnostic; exhaustive bounded propositional semantics.

No NL parsing, code execution, extra world facts or new API calls. The input
program has already passed the ORIGINAL schema and citation validator.
Inconsistent theories return UNKNOWN, never an arbitrary logical explosion.
This replay is not a new held-out architecture or a certified NL compiler.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "src"), str(HERE.parent / "three_architectures")]
from guardian_truth.formal_reasoning import parse_formalization  # noqa: E402


def solve_classical(program):
    if program.status == "UNSUPPORTED":
        return {"relation": "INSUFFICIENT", "reason": "unsupported_translation"}
    positions = {atom.id: i for i, atom in enumerate(program.atoms)}
    if len(positions) > 16:
        raise ValueError("bounded atom limit exceeded")

    def truth(literal, state):
        bit = bool(state & (1 << positions[literal.atom_id]))
        return bit if literal.polarity == "POS" else not bit

    def accepts_rule(rule, state):
        cond = all(truth(literal, state) for literal in rule.conditions)
        conclusion = truth(rule.conclusion, state)
        forward = not cond or conclusion
        backward = not conclusion or cond
        return (forward if rule.direction == "IF" else backward if
                rule.direction == "ONLY_IF" else forward and backward)

    values = set()
    for state in range(1 << len(positions)):
        if not all(truth(fact.literal, state) for fact in program.facts):
            continue
        if not all(accepts_rule(rule, state) for rule in program.rules):
            continue
        values.add(truth(program.query, state))
        if len(values) == 2:
            return {"relation": "INSUFFICIENT", "reason": "both_query_values_possible"}
    if not values:
        return {"relation": "INSUFFICIENT", "reason": "inconsistent_theory"}
    return {"relation": "FOLLOWS" if True in values else "CONTRADICTS",
            "reason": "all_consistent_models_agree"}


def run(folder, output):
    config = json.loads((folder / "run_config.json").read_text(encoding="utf-8"))
    status = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    if status["state"] != "SUCCEEDED" or config["split"] != "dev":
        raise ValueError("diagnostic only accepts completed dev translations")
    source = HERE / "dataset/fresh_v1/dev_input.jsonl"
    if hashlib.sha256(source.read_bytes()).hexdigest() != config["input_sha256"]:
        raise ValueError("input hash mismatch")
    cases = {r["id"]: r for r in map(json.loads, source.read_text(encoding="utf-8").splitlines())}
    records = [json.loads(line) for line in (folder / "results.jsonl").read_text(
        encoding="utf-8").splitlines()]
    if [r["id"] for r in records] != config["case_ids"]:
        raise ValueError("incomplete translation journal")
    result = {"schema": "fixed-ir-classical-probe/1", "source_run": status["run_id"],
        "input_sha256": config["input_sha256"], "gold_read": False,
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "warning": "Stronger backend relative to the same unverified translation, not better NL meaning.",
        "records": []}
    for record in records:
        outcome = {"relation": "INSUFFICIENT", "reason": "invalid_original_translation"}
        if record["status"] == "VALID":
            case = cases[record["id"]]
            program = parse_formalization(json.dumps(record["translation"], ensure_ascii=False),
                [{"id": "prompt", "text": case["prompt"]}, {"id": "target", "text": case["response"]}])
            outcome = solve_classical(program)
        result["records"].append({"id": record["id"], "horn": record["relation"], **outcome})
    result["counts"] = {relation: sum(r["relation"] == relation for r in result["records"])
                        for relation in ("FOLLOWS", "CONTRADICTS", "INSUFFICIENT")}
    result["changed"] = [r for r in result["records"] if r["horn"] != r["relation"]]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = run(args.source, args.output)
    print(json.dumps({"counts": result["counts"], "changed": result["changed"]}, indent=2))

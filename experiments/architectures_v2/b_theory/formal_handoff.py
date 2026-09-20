"""Per-theory handoff to the unchanged Full Architecture N5 path."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

from guardian_truth.parsing import parse_catalog, parse_events


def _identity(value) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^\w]+", "_", unicodedata.normalize("NFKC", value).casefold(),
                  flags=re.UNICODE).strip("_")


def _read_cases(path: Path) -> dict[str, dict]:
    if path.suffix.lower() == ".csv":
        csv.field_size_limit(16 * 1024 * 1024)
        with path.open(encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))
    else:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    result = {}
    for row in rows:
        if not {"id", "prompt", "response"} <= set(row):
            raise ValueError("case input requires id,prompt,response")
        case_id = str(row["id"])
        if case_id in result:
            raise ValueError(f"duplicate case id: {case_id}")
        result[case_id] = {"id": case_id, "prompt": str(row["prompt"]),
                           "response": str(row["response"])}
    return result


def _valid_spans(rule: dict, case: dict) -> tuple[bool, str]:
    spans = rule.get("source_spans", [])
    if not spans:
        return False, "NO_SOURCE_SPANS"
    for span in spans:
        document = span.get("document")
        text = case.get(document) if document in {"prompt", "response"} else None
        try:
            start, end, quote = int(span["start"]), int(span["end"]), span["quote"]
        except (KeyError, TypeError, ValueError):
            return False, "INVALID_SOURCE_SPAN"
        if text is None or not isinstance(quote, str) or not quote or not 0 <= start < end <= len(text):
            return False, "INVALID_SOURCE_SPAN"
        if text[start:end] != quote:
            return False, "SOURCE_SPAN_MISMATCH"
    return True, "ANCHORED"


def _tool_names(prompt: str) -> tuple[str, ...]:
    catalog = parse_catalog(parse_events(prompt, "prompt"), prompt)
    return tuple(catalog.tools)


def _binding(rule: dict, tool_names: tuple[str, ...]) -> dict:
    target = rule.get("target") or {}
    text, ref = target.get("text"), target.get("ref", "UNKNOWN")
    text_key = _identity(text)
    matches = [name for name in tool_names if _identity(name) == text_key]
    if (len(matches) == 1 and text_key
            and (ref == "UNKNOWN" or _identity(ref) == text_key)):
        return {"status": "BOUND", "semantic_text": text,
                "candidates": [{"name": matches[0], "method": "exact"}]}
    return {"status": "UNKNOWN", "semantic_text": text, "candidates": []}


def run_formal_handoff(case: dict, b_record: dict, *, run_arm_fn=None) -> dict:
    """Run each whole theory separately; never union provider alternatives."""
    if run_arm_fn is None:
        try:
            from experiments.full_architecture_v1.pipeline import run_arm
        except ImportError as exc:
            raise RuntimeError(f"existing FullArch N5 runtime unavailable: {exc}") from exc
        run_arm_fn = run_arm
    if case["id"] != b_record.get("case_id"):
        raise ValueError("case id mismatch")
    tools = _tool_names(case["prompt"])
    alternatives = []
    for theory in b_record.get("candidates", []):
        rules, losses = [], []
        eligible_theory = theory.get("candidate_status") == "ELIGIBLE_HYPOTHESIS"
        if not eligible_theory:
            losses.append({"element_id": None, "status": "REJECTED",
                           "reason": "THEORY_NOT_ELIGIBLE"})
        for element in theory.get("elements", []) if eligible_theory else ():
            boundary = element.get("ruleir_boundary") or {}
            if boundary.get("status") != "BINDING_REQUIRED" or not boundary.get("rule_ir"):
                losses.append({"element_id": element.get("element_id"),
                               "status": boundary.get("status", "MISSING"),
                               "reason": boundary.get("reason", "NO_RULE_IR")})
                continue
            rule = boundary["rule_ir"]
            grounded, reason = _valid_spans(rule, case)
            if not grounded:
                losses.append({"element_id": element.get("element_id"),
                               "status": "REJECTED", "reason": reason})
                continue
            rules.append({"rule_id": rule["rule_id"],
                          "extractor": (rule.get("provenance") or {}).get(
                              "extractor", "deterministic"),
                          "rule": rule, "binding": _binding(rule, tools)})
        exact_bound = sum(item["binding"]["status"] == "BOUND" for item in rules)
        if rules:
            phi = {"case_id": case["id"], "frontend_hash": "architecture-b-exact-handoff",
                   "candidates": rules}
            result = run_arm_fn(case, phi, "N5")
        else:
            result = {"status": "UNRESOLVED", "binary": 0, "checker_ok": None,
                      "checker_failures": [], "markers": ["phi-empty:no-eligible-rules"],
                      "runtime_s": 0.0, "rules_lowered": 0, "interpretations": 0}
        alternatives.append({
            "candidate_id": theory.get("candidate_id"), "provider": theory.get("provider"),
            "representable_rules": len(rules), "exact_bound_rules": exact_bound,
            "losses": losses, "n5": result,
        })
    return {"case_id": case["id"], "variant": b_record.get("variant"),
            "alternatives": alternatives,
            "combination_policy": "NO_UNION_EACH_THEORY_RUN_SEPARATELY",
            "label_free": True}


def run_cli(args) -> int:
    case_path, b_path = Path(args.input).resolve(strict=True), Path(args.b_records).resolve(strict=True)
    output = Path(args.output).resolve()
    cases = _read_cases(case_path)
    b_rows = [json.loads(line) for line in b_path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    fingerprint = hashlib.sha256(
        (hashlib.sha256(case_path.read_bytes()).hexdigest() +
         hashlib.sha256(b_path.read_bytes()).hexdigest()).encode()).hexdigest()
    completed = set()
    if output.exists():
        prior = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        if any(row.get("run_fingerprint") != fingerprint for row in prior):
            raise ValueError("resume fingerprint differs from existing output")
        completed = {row["case_id"] for row in prior}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8", newline="\n") as destination:
        for row in b_rows:
            case_id = row.get("case_id")
            if case_id in completed:
                continue
            if case_id not in cases:
                raise ValueError(f"B record has unknown case id: {case_id}")
            result = run_formal_handoff(cases[case_id], row)
            destination.write(json.dumps({**result, "run_fingerprint": fingerprint},
                                         ensure_ascii=False, sort_keys=True) + "\n")
            destination.flush()
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="label-free id,prompt,response CSV/JSONL")
    parser.add_argument("--b-records", required=True, help="run_b_theory records.jsonl")
    parser.add_argument("--output", required=True, help="append-only N5 result JSONL")
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        raise SystemExit(run_cli(parse_args()))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"b_formal_handoff: {exc}", file=sys.stderr)
        raise SystemExit(2)

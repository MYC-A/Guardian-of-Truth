"""Offline comparison of frozen A/B/C architecture artifacts.

A may be the historical claim-gate format (``strict``/``overall`` decisions).
B and C may use the generic ``benchmark_architecture.py`` audit format.  The
utility never calls a model and computes label metrics from row records rather
than trusting a report summary.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from guardian_truth.benchmarking import metrics
from guardian_truth.parsing import decode_json


def _read_json(path: Path):
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise ValueError(f"Cannot read {path}") from None
    value, valid = decode_json(raw)
    if not valid or not isinstance(value, dict):
        raise ValueError(f"Invalid JSON object: {path}")
    return value


def _read_jsonl(path: Path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise ValueError(f"Cannot read {path}") from None
    records = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        value, valid = decode_json(line)
        if not valid or not isinstance(value, dict):
            raise ValueError(f"Invalid JSONL record {number}: {path}")
        records.append(value)
    if not records:
        raise ValueError(f"Empty audit: {path}")
    return records


def _fixed_ids(path: Path | None):
    if path is None:
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise ValueError(f"Cannot read {path}") from None
    value, valid = decode_json(raw)
    if not valid:
        raise ValueError("Invalid fixed IDs")
    if isinstance(value, dict) and set(value) == {"ids"}:
        value = value["ids"]
    if (not isinstance(value, list) or not value
            or any(not isinstance(item, str) or not item for item in value)
            or len(value) != len(set(value))):
        raise ValueError("Invalid fixed IDs")
    return value


def _binary(value, field):
    if type(value) is not int or value not in (0, 1):
        raise ValueError(f"Invalid {field}")
    return value


def _nonnegative(value):
    return type(value) in (int, float) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _row_decision(record, branch):
    if "prediction" in record:
        prediction = _binary(record["prediction"], "prediction")
        decision = record.get("decision")
        fallback = decision.get("used_fallback") if isinstance(decision, dict) else None
    elif branch in record and isinstance(record[branch], dict):
        prediction = _binary(record[branch].get("label"), f"{branch}.label")
        fallback = record[branch].get("used_fallback")
    elif isinstance(record.get("decision"), dict):
        prediction = _binary(record["decision"].get("label"), "decision.label")
        fallback = record["decision"].get("used_fallback")
    else:
        raise ValueError("Audit row has no supported decision")
    if type(fallback) is not bool:
        raise ValueError("Audit row has no valid fallback flag")
    return prediction, fallback


def _selected_records(records, selected):
    by_id = {}
    for raw in records:
        identifier = raw.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in by_id:
            raise ValueError("Invalid or duplicate audit ID")
        by_id[identifier] = raw
    ids = list(by_id) if selected is None else selected
    if any(identifier not in by_id for identifier in ids):
        raise ValueError("Fixed ID absent from an audit")
    return [by_id[identifier] for identifier in ids], len(ids) == len(records)


def _report_number(report, paths):
    for path in paths:
        value = report
        for key in path:
            if not isinstance(value, dict) or key not in value:
                value = None
                break
            value = value[key]
        if _nonnegative(value):
            return value
    return None


def _row_sum(records, getter):
    values = [getter(record) for record in records]
    if not all(_nonnegative(value) for value in values):
        return None
    return sum(values)


def _cost(records, report, full_selection):
    def logical(record):
        if _nonnegative(record.get("logical_llm_calls")):
            return record["logical_llm_calls"]
        review = record.get("review")
        trace = review.get("reading_trace") if isinstance(review, dict) else None
        if not isinstance(trace, list):
            return None
        return sum(1 for item in trace if isinstance(item, dict)
                   and (item.get("round") is not None
                        or item.get("stage") in ("extractor", "semantic_verifier", "final_judge"))
                   and item.get("call", 1) is not None)

    def tokens(record):
        review = record.get("review")
        usage = review.get("semantic_usage") if isinstance(review, dict) else None
        return usage.get("total_tokens") if isinstance(usage, dict) else None

    values = {
        "logical_llm_calls": _row_sum(records, logical),
        "http_attempts": _row_sum(records, lambda row: row.get("http_attempts")),
        "reported_tokens": _row_sum(records, tokens),
        "elapsed_seconds": _row_sum(records, lambda row: row.get("elapsed_seconds")),
    }
    sources = {key: "audit_rows" if value is not None else None for key, value in values.items()}
    report_paths = {
        "logical_llm_calls": (("metrics", "logical_llm_calls"),),
        "http_attempts": (("metrics", "http_attempts"), ("budget", "requests")),
        "reported_tokens": (("metrics", "reported_tokens"), ("reported_total_tokens",)),
        "elapsed_seconds": (("metrics", "elapsed_seconds"), ("budget", "seconds")),
    }
    if full_selection:
        for key, paths in report_paths.items():
            if values[key] is None:
                values[key] = _report_number(report, paths)
                if values[key] is not None:
                    sources[key] = "report"
    result = {}
    for key in values:
        result[key] = {"value": values[key], "source": sources[key]}
    calls = values["logical_llm_calls"]
    tokens_total = values["reported_tokens"]
    elapsed = values["elapsed_seconds"]
    count = len(records)
    result["per_row"] = {
        "logical_llm_calls": calls / count if calls is not None else None,
        "reported_tokens": tokens_total / count if tokens_total is not None else None,
        "elapsed_seconds": elapsed / count if elapsed is not None else None,
    }
    return result


def _structured(records):
    semantic = [record for record in records if record.get("skipped_mechanical") is not True]
    valid = 0
    for record in semantic:
        review = record.get("review")
        if isinstance(review, dict) and type(review.get("semantic_score")) in (int, float):
            score = review["semantic_score"]
            if not isinstance(score, bool) and math.isfinite(score):
                valid += 1
    return {"valid_rows": valid, "semantic_rows": len(semantic),
            "rate": valid / len(semantic) if semantic else None}


def _deterministic(records):
    if not all("ledger" in record for record in records):
        return {"available": False, "contradicted_checks": None,
                "caught_rows": None, "row_ids": None}
    caught, checks = [], 0
    for record in records:
        ledger = record["ledger"]
        if ledger is None:
            ledger = []
        if not isinstance(ledger, list):
            raise ValueError("Invalid ledger")
        count = sum(1 for item in ledger if isinstance(item, dict)
                    and item.get("verifier") == "deterministic"
                    and item.get("relation") == "CONTRADICTED")
        checks += count
        if count:
            caught.append(record["id"])
    return {"available": True, "contradicted_checks": checks,
            "caught_rows": len(caught), "row_ids": caught}


def load_run(name, audit_path, report_path, selected=None, *, branch="strict"):
    raw_records = _read_jsonl(audit_path)
    records, full_selection = _selected_records(raw_records, selected)
    report = _read_json(report_path)
    normalized = []
    for raw in records:
        prediction, fallback = _row_decision(raw, branch)
        normalized.append({"id": raw["id"], "gold": _binary(raw.get("label"), "label"),
                           "prediction": prediction, "fallback": fallback, "raw": raw})
    summary = metrics([row["gold"] for row in normalized],
                      [row["prediction"] for row in normalized])
    summary["fallback"] = sum(row["fallback"] for row in normalized)
    return {
        "name": name, "rows": normalized, "report": report,
        "full_selection": full_selection,
        "metrics": summary,
        "cost": _cost(records, report, full_selection),
        "structured_output": _structured(records),
        "deterministic_catches": _deterministic(records),
    }


def _reason_precision(rows, field):
    if not rows or not any(field in row for row in rows):
        return None
    good = sum(row.get(field) is True for row in rows)
    bad = sum(row.get(field) is False for row in rows)
    unknown = len(rows) - good - bad
    denominator = len(rows)
    return {
        "denominator": denominator,
        "verified_correct": good,
        "verified_wrong": bad,
        "unadjudicated": unknown,
        "verified_lower_bound": good / denominator,
        "possible_upper_bound": (good + unknown) / denominator,
        "audited_precision": good / (good + bad) if good + bad else None,
        "audit_coverage": (good + bad) / denominator,
    }


def load_reason_audit(path, run):
    expected = {row["id"]: row for row in run["rows"]}
    semantic_positive = {row["id"] for row in run["rows"]
                         if row["prediction"] == 1
                         and row["raw"].get("skipped_mechanical") is not True}
    if path is None:
        return {"available": False, "rows_audited": None,
                "semantic_positive_rows": len(semantic_positive), "coverage": None,
                "reason_precision": None, "cited_reason_precision": None,
                "categories": None, "wrong_reason_tp": None}
    payload = _read_json(path)
    audit_rows = payload.get("rows")
    if isinstance(audit_rows, list):
        selected, seen = [], set()
        for row in audit_rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise ValueError("Invalid reason audit row")
            identifier = row["id"]
            if identifier not in expected:
                continue
            if identifier in seen or identifier not in semantic_positive:
                raise ValueError("Reason audit row is duplicate or not a semantic-positive decision")
            seen.add(identifier)
            gold = row.get("label", row.get("gold"))
            if gold is not None and _binary(gold, "reason gold") != expected[identifier]["gold"]:
                raise ValueError("Reason audit gold mismatch")
            prediction = row.get("prediction")
            if prediction is not None and _binary(prediction, "reason prediction") != expected[identifier]["prediction"]:
                raise ValueError("Reason audit prediction mismatch")
            selected.append(row)
        categories = Counter()
        wrong_reason_tp = 0
        for row in selected:
            valid = row.get("material_valid_reason")
            gold, prediction = expected[row["id"]]["gold"], expected[row["id"]]["prediction"]
            if prediction != gold:
                categories["WRONG_LABEL"] += 1
            elif valid is True:
                categories["CORRECT_LABEL_CORRECT_REASON"] += 1
            elif valid is False:
                categories["CORRECT_LABEL_WRONG_REASON"] += 1
                if gold == prediction == 1:
                    wrong_reason_tp += 1
            else:
                categories["UNADJUDICATED_REASON_TP"] += 1
        return {
            "available": True,
            "rows_audited": len(selected),
            "semantic_positive_rows": len(semantic_positive),
            "coverage": len(selected) / len(semantic_positive) if semantic_positive else None,
            "reason_precision": _reason_precision(selected, "material_valid_reason"),
            "cited_reason_precision": _reason_precision(selected, "cited_material_valid_reason"),
            "categories": dict(categories),
            "wrong_reason_tp": wrong_reason_tp,
        }
    summary = payload.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("metrics"), dict):
        summary = summary["metrics"]
    if not isinstance(summary, dict):
        raise ValueError("Reason audit has neither rows nor summary")
    # Summary-only compatibility: copy only fields actually present. It cannot
    # establish row coverage or be safely re-scoped to a fixed subset.
    return {
        "available": True,
        "rows_audited": None,
        "semantic_positive_rows": len(semantic_positive),
        "coverage": None,
        "reason_precision": summary.get("reason_precision"),
        "cited_reason_precision": summary.get("cited_reason_precision"),
        "categories": summary.get("semantic_positive_categories", summary.get("categories")),
        "wrong_reason_tp": summary.get("wrong_reason_tp"),
    }


def _transition(left, right):
    lhs = {row["id"]: row for row in left["rows"]}
    rhs = {row["id"]: row for row in right["rows"]}
    changed, corrected, regressed = [], [], []
    for identifier in lhs:
        before, after = lhs[identifier], rhs[identifier]
        if before["prediction"] == after["prediction"]:
            continue
        item = {"id": identifier, "gold": before["gold"],
                "from": before["prediction"], "to": after["prediction"]}
        changed.append(item)
        if before["prediction"] != before["gold"] and after["prediction"] == after["gold"]:
            corrected.append(item)
        elif before["prediction"] == before["gold"] and after["prediction"] != after["gold"]:
            regressed.append(item)
    return {"changed": changed, "corrected": corrected, "regressed": regressed,
            "counts": {"changed": len(changed), "corrected": len(corrected),
                       "regressed": len(regressed)}}


def compare(a, b, c, *, reason_paths=None, fixed_ids=None):
    runs = {"A": a, "B": b, "C": c}
    reference = [(row["id"], row["gold"]) for row in a["rows"]]
    for name, run in runs.items():
        if [(row["id"], row["gold"]) for row in run["rows"]] != reference:
            raise ValueError(f"{name} audit IDs/order/gold labels do not match A")
    reason_paths = reason_paths or {}
    architectures = {}
    for name, run in runs.items():
        architectures[name] = {
            "metrics": run["metrics"],
            "cost": run["cost"],
            "structured_output": run["structured_output"],
            "deterministic_catches": run["deterministic_catches"],
            "reason_audit": load_reason_audit(reason_paths.get(name), run),
        }
    return {
        "scope": {"rows": len(reference), "ids": [item[0] for item in reference],
                  "fixed_ids_applied": fixed_ids is not None},
        "architectures": architectures,
        "transitions": {
            "A_to_B": _transition(a, b),
            "A_to_C": _transition(a, c),
            "B_to_C": _transition(b, c),
        },
        "limitations": [
            "Metrics describe only the selected rows; an error-heavy slice is not a leaderboard estimate.",
            "Reason Precision is reported only from an explicit reason-audit artifact.",
            "Report-only aggregate cost is omitted when fixed IDs select a strict subset.",
        ],
    }


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("a", "b", "c"):
        parser.add_argument(f"--{name}-audit", type=Path, required=True)
        parser.add_argument(f"--{name}-report", type=Path, required=True)
        parser.add_argument(f"--{name}-reason-audit", type=Path)
    parser.add_argument("--ids-file", type=Path)
    parser.add_argument("--a-branch", choices=("strict", "overall"), default="strict")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Use a new output file")
    try:
        selected = _fixed_ids(args.ids_file)
        a = load_run("A", args.a_audit, args.a_report, selected, branch=args.a_branch)
        b = load_run("B", args.b_audit, args.b_report, selected)
        c = load_run("C", args.c_audit, args.c_report, selected)
        result = compare(a, b, c, reason_paths={
            "A": args.a_reason_audit, "B": args.b_reason_audit, "C": args.c_reason_audit,
        }, fixed_ids=selected)
        inputs = [args.a_audit, args.a_report, args.b_audit, args.b_report,
                  args.c_audit, args.c_report]
        inputs += [path for path in (args.ids_file, args.a_reason_audit,
                                     args.b_reason_audit, args.c_reason_audit) if path is not None]
        result["input_sha256"] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in inputs}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
    except (ValueError, OSError) as error:
        parser.error(str(error))
    return result


if __name__ == "__main__":
    main()


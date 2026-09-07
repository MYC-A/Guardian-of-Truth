"""Run a bounded C/D shadow screen with gold isolated from model messages."""

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import time

from guardian_truth.formal_reasoning import (
    FormalValidationError, parse_formalization, solve, validate_applicability,
)
from guardian_truth.formal_translation import (
    build_application_messages, build_formal_messages, schema_for,
)
from guardian_truth.language import BudgetExceeded, RunBudget
from guardian_truth.llm_client import ChatClient, ChatClientError, ClientConfig
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file
from benchmark_claim_relations import AuditedTransport, Pacer


MAX_INPUT_BYTES = 4 * 1024 * 1024


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False,
                      separators=(",", ":"))


def _hash_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def load_cases(path):
    raw = Path(path).read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Input too large")
    payload = json.loads(raw, object_pairs_hook=_unique_object,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError("Invalid cases")
    seen = set()
    for case in cases:
        required = {"id", "method", "target", "rule", "evidence", "gold_output", "tags"}
        if not isinstance(case, dict) or set(case) != required:
            raise ValueError("Invalid case")
        if (not isinstance(case["id"], str) or not case["id"].strip()
                or case["id"] in seen or case["method"] not in ("C", "D")
                or not isinstance(case["gold_output"], str)
                or not isinstance(case["tags"], list)
                or any(not isinstance(tag, str) for tag in case["tags"])):
            raise ValueError("Invalid case")
        if case["method"] == "C" and not isinstance(case["rule"], str):
            raise ValueError("C requires a supplied rule")
        if case["method"] == "D" and case["rule"] is not None:
            raise ValueError("D does not accept a supplied rule")
        # Builders perform the same bounded input validation used for requests.
        messages(case)
        seen.add(case["id"])
    return cases, _hash_bytes(raw)


def messages(case):
    if case["method"] == "D":
        return build_formal_messages(case["target"], case["evidence"])
    return build_application_messages(case["target"], case["rule"], case["evidence"])


def _normalized_formal(program):
    ordered = sorted(program.atoms, key=lambda atom: (atom.text, atom.entity_refs,
                                                       atom.time_refs, atom.id))
    names = {atom.id: "v" + str(index) for index, atom in enumerate(ordered)}

    def lit(value):
        return (names[value.atom_id], value.polarity)

    return {
        "status": program.status,
        "atoms": sorted((names[item.id], item.text, item.entity_refs, item.time_refs)
                        for item in program.atoms),
        "facts": sorted((lit(item.literal), tuple((s.source_id, s.quote) for s in item.sources))
                        for item in program.facts),
        "rules": sorted((item.direction, tuple(sorted(lit(x) for x in item.conditions)),
                         lit(item.conclusion), tuple((s.source_id, s.quote) for s in item.sources))
                        for item in program.rules),
        "query": lit(program.query) if program.query is not None else None,
    }


def parse_output(case, raw):
    if case["method"] == "D":
        program = parse_formalization(raw, case["evidence"])
        result = solve(program)
        normalized = _normalized_formal(program)
        return result.relation, _hash_bytes(_json(normalized).encode()), asdict(result)
    result = validate_applicability(raw, case["evidence"])
    payload = json.loads(raw, object_pairs_hook=_unique_object,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    return result.applicability, _hash_bytes(_json(payload).encode()), asdict(result)


def token_usage(usage):
    return {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if type(usage.get(key)) is int and usage[key] >= 0}


def write_line(stream, value):
    stream.write(_json(value) + "\n")
    stream.flush()


def summarize(records):
    valid = [row for row in records if row["status"] == "valid"]
    by_method = {}
    for method in ("C", "D"):
        subset = [row for row in records if row["method"] == method]
        good = [row for row in subset if row["status"] == "valid"]
        correct = sum(row["output"] == row["gold_output"] for row in good)
        by_method[method] = {"attempted": len(subset), "valid": len(good),
                             "correct": correct,
                             "accuracy_all": correct / len(subset) if subset else None}
    groups = defaultdict(list)
    for row in records:
        groups[row["case_id"]].append(row)
    stability = {}
    for case_id, rows in sorted(groups.items()):
        valid_rows = [row for row in rows if row["status"] == "valid"]
        stability[case_id] = {
            "runs": len(rows), "valid": len(valid_rows),
            "same_output": len({row["output"] for row in valid_rows}) <= 1 if valid_rows else None,
            "same_normalized_translation": len({row["normalized_sha256"] for row in valid_rows}) <= 1
                                           if valid_rows else None,
        }
    correct = sum(row["output"] == row["gold_output"] for row in valid)
    return {"attempted": len(records), "valid": len(valid), "correct": correct,
            "accuracy_all": correct / len(records) if records else None,
            "status_counts": dict(Counter(row["status"] for row in records)),
            "by_method": by_method, "stability": stability,
            "limitations": [
                "This is target-level inspected development evidence, not autonomous row-level F1.",
                "Solver soundness is relative to the model translation; exact quotes do not prove semantic faithfulness.",
                "Synthetic controls test known failure modes but do not estimate hidden-test quality.",
            ]}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--provider", choices=("groq", "openrouter", "gemini"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--method", choices=("C", "D"), action="append",
                        help="Optional method filter; repeat to select both")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--interval-seconds", type=float, default=20)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--max-requests", type=int, default=30)
    parser.add_argument("--seconds", type=float, default=1200)
    parser.add_argument("--max-input-chars", type=int, default=1_000_000)
    parser.add_argument("--retries", type=int, default=1)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.output_dir.exists() or not 1 <= args.repetitions <= 3:
        raise SystemExit("Use a new output directory and 1..3 repetitions")
    cases, input_hash = load_cases(args.input)
    if args.method:
        selected = set(args.method)
        cases = [case for case in cases if case["method"] in selected]
        if not cases:
            raise SystemExit("Method filter selected no cases")
    load_env_file(args.env_file)
    initial = ClientConfig.from_env()
    selected_url = initial.base_url if args.provider == "groq" else None
    config = provider_config(initial, args.provider, model=args.model, base_url=selected_url)
    config = replace(config, max_output_tokens=args.max_output_tokens,
                     max_retries=args.retries, strict_schema=False)
    budget = RunBudget(args.max_requests, args.max_input_chars, args.seconds)
    pacer = Pacer(args.interval_seconds)
    ChatClient(config).validate_configuration()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    configuration = {
        "provider": args.provider, "model": config.model, "base_url": config.base_url,
        "input_sha256": input_hash, "cases": len(cases), "repetitions": args.repetitions,
        "selected_case_ids": [case["id"] for case in cases],
        "interval_seconds": args.interval_seconds, "max_requests": args.max_requests,
        "max_input_chars": args.max_input_chars, "seconds": args.seconds,
        "schema_sha256": {method: _hash_bytes(_json(schema_for(method)).encode())
                          for method in ("C", "D")},
        "scope": "shadow target-level formal-method screen; no production labels changed",
    }
    (args.output_dir / "configuration.json").write_text(
        json.dumps(configuration, indent=2, ensure_ascii=True), encoding="utf-8")
    records = []
    with (args.output_dir / "attempts.jsonl").open("x", encoding="utf-8") as attempts, \
         (args.output_dir / "calls.jsonl").open("x", encoding="utf-8") as calls:
        audited = AuditedTransport(attempts, pacer, budget)
        client = ChatClient(config, transport=audited)
        exhausted = False
        for repetition in range(1, args.repetitions + 1):
            for case in cases:
                row = {"case_id": case["id"], "method": case["method"],
                       "repetition": repetition, "gold_output": case["gold_output"],
                       "tags": case["tags"], "status": "budget_exceeded", "output": None,
                       "normalized_sha256": None, "result": None, "usage": {},
                       "raw_response": None, "response_model": None,
                       "http_attempts_reserved": 0, "error_category": None}
                before, started = budget.requests, time.monotonic()
                try:
                    if exhausted:
                        raise BudgetExceeded("Run budget exhausted")
                    audited.case_id = case["id"] + "::r" + str(repetition)
                    completion = client.complete(messages(case),
                                                 schema=schema_for(case["method"]),
                                                 budget=budget)
                    row["raw_response"] = completion.content
                    row["response_model"] = completion.model
                    row["usage"] = token_usage(completion.usage)
                    output, normalized, result = parse_output(case, completion.content)
                    row.update(status="valid", output=output,
                               normalized_sha256=normalized, result=result)
                except FormalValidationError as error:
                    row.update(status="invalid_output", error_category=error.category)
                except (ValueError, TypeError, RecursionError):
                    row.update(status="invalid_output", error_category="invalid_output")
                except BudgetExceeded:
                    exhausted = True
                    row.update(status="budget_exceeded", error_category="budget_exceeded")
                except ChatClientError as error:
                    row.update(status="api_error", error_category=error.category)
                row["http_attempts_reserved"] = budget.requests - before
                row["elapsed_seconds"] = max(0, time.monotonic() - started)
                write_line(calls, row)
                records.append(row)
                print(_json({"case": case["id"], "repetition": repetition,
                             "status": row["status"], "output": row["output"]}), flush=True)
    report = summarize(records)
    report["budget"] = budget.summary()
    report["input_sha256"] = input_hash
    report["model"] = config.model
    (args.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(_json({"output_dir": str(args.output_dir), "valid": report["valid"],
                 "accuracy_all": report["accuracy_all"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

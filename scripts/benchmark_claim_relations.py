"""Run one semantic judge on frozen claim/evidence cases, with shadow-only audit.

Gold relations and tags are used only in the local report. They never enter a
model message. All models use temperature=0, json_object, and the same prompt;
native reasoning settings are neither supplied nor changed.
"""

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import time

from guardian_truth.claim_verifier import (
    INSTRUCTION, VERDICTS, VerificationError, build_messages, parse_verification,
)
from guardian_truth.language import BudgetExceeded, RunBudget
from guardian_truth.llm_client import (
    ChatClient, ChatClientError, ClientConfig, _http_transport,
)
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file


MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_CASES = 1000


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Nonfinite JSON number")


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False)


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _tags(case):
    return sorted(set(case.get("tags", []) + case.get("audit_tags", [])))


def load_cases(path):
    """Validate the entire frozen input before creating artifacts or requesting."""
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Frozen input exceeds size limit")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object,
                             parse_constant=_reject_constant)
        cases = payload["cases"]
        if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
            raise ValueError
        ids = set()
        for case in cases:
            if not isinstance(case, dict):
                raise ValueError
            for key in ("id", "row_id"):
                if not isinstance(case.get(key), str) or not case[key].strip():
                    raise ValueError
            if case["id"] in ids or case.get("gold_relation") not in VERDICTS:
                raise ValueError
            ids.add(case["id"])
            for key in ("tags", "audit_tags"):
                if key in case and (not isinstance(case[key], list)
                                    or any(not isinstance(t, str) or not t.strip()
                                           for t in case[key])):
                    raise ValueError
            messages = build_messages(case["claim"], case["evidence"], case.get("candidate_response"))
            if ("messages_sha256" in case
                    and case["messages_sha256"] != _hash(_json(messages).encode())):
                raise ValueError
        return cases, _hash(raw)
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ValueError("Invalid frozen claim case input") from None


class Pacer:
    """Minimum spacing between request starts; all sleeps are at most one second."""

    def __init__(self, interval, *, clock=time.monotonic, sleep=time.sleep):
        if (type(interval) not in (int, float) or not math.isfinite(interval)
                or interval < 0):
            raise ValueError("Invalid interval")
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self.last_start = None

    def wait(self, budget):
        while True:
            remaining_budget = budget.remaining_seconds()
            remaining = (0 if self.last_start is None else
                         self.last_start + self.interval - self.clock())
            if remaining <= 0:
                self.last_start = self.clock()
                return
            self.sleep(min(1.0, remaining, remaining_budget))


def _write_line(stream, row):
    stream.write(_json(row) + "\n")
    stream.flush()


class AuditedTransport:
    """Pace and flush each HTTP attempt, including retries, without server data."""

    def __init__(self, stream, pacer, budget, *, transport=None,
                 clock=time.monotonic):
        self.stream, self.pacer, self.budget = stream, pacer, budget
        self.transport, self.clock = transport or _http_transport, clock
        self.case_id = None
        self.attempts = 0

    def __call__(self, request, timeout):
        # ChatClient reserves this attempt before entering transport. A deadline
        # reached while pacing must prevent network I/O and remain auditable.
        self.attempts += 1
        record = {"attempt": self.attempts, "case_id": self.case_id,
                  "started_monotonic": self.clock(), "status": "waiting"}
        try:
            self.pacer.wait(self.budget)
            timeout = min(timeout, self.budget.remaining_seconds())
            record["request_started_monotonic"] = self.clock()
            response = self.transport(request, timeout)
            record["status"] = "http_response"
            record["http_status"] = response.status
            return response
        except BudgetExceeded:
            record["status"] = "budget_exceeded_before_http"
            raise
        except Exception:
            record["status"] = "transport_exception"
            raise
        finally:
            record["elapsed_seconds"] = max(0, self.clock() - record["started_monotonic"])
            _write_line(self.stream, record)


def summarize(records):
    """Gold-relation metrics; no automatic claims about rationale correctness."""
    total = len(records)
    valid = [row for row in records if row["status"] == "valid"]
    correct = sum(row["relation"] == row["gold_relation"] for row in valid)
    confusion = {gold: {pred: 0 for pred in (*VERDICTS, "INVALID_OR_ERROR")}
                 for gold in VERDICTS}
    for row in records:
        predicted = row["relation"] if row["status"] == "valid" else "INVALID_OR_ERROR"
        confusion[row["gold_relation"]][predicted] += 1
    entailed = [row for row in valid if row["relation"] == "ENTAILED"]
    entailed_correct = sum(row["gold_relation"] == "ENTAILED" for row in entailed)
    tagged = {}
    for tag in ("entity_confusion", "wrong_polarity"):
        subset = [row for row in records if tag in row["tags"]]
        valid_subset = [row for row in subset if row["status"] == "valid"]
        wrong = sum(row["relation"] != row["gold_relation"] for row in valid_subset)
        errors = wrong + len(subset) - len(valid_subset)
        tagged[tag] = {
            "definition": "Relation-error rate among input cases tagged " + tag
                          + "; not a diagnosis of generated rationale.",
            "cases": len(subset), "valid": len(valid_subset),
            "wrong_relations": wrong, "invalid_or_error": len(subset) - len(valid_subset),
            "error_rate_all": errors / len(subset) if subset else None,
            "error_rate_valid": wrong / len(valid_subset) if valid_subset else None,
        }
    decisive_gold = [row for row in valid if row["gold_relation"] in ("ENTAILED", "CONTRADICTED")]
    flips = sum({row["relation"], row["gold_relation"]} == {"ENTAILED", "CONTRADICTED"}
                for row in decisive_gold)
    return {
        "cases": total, "valid": len(valid), "correct": correct,
        "status_counts": dict(Counter(row["status"] for row in records)),
        "accuracy_all": correct / total if total else None,
        "accuracy_valid": correct / len(valid) if valid else None,
        "confusion_gold_rows_prediction_columns": confusion,
        "entailed_precision_proxy": {
            "definition": "Gold ENTAILED among valid predicted ENTAILED; claim-level precision, not Reason Precision.",
            "predicted_entailed": len(entailed), "gold_entailed": entailed_correct,
            "precision": entailed_correct / len(entailed) if entailed else None,
        },
        "tagged_challenge_error_rates": tagged,
        "direct_polarity_flips": {
            "definition": "ENTAILED predicted as CONTRADICTED or reverse, divided by valid cases with decisive gold.",
            "count": flips, "denominator": len(decisive_gold),
            "rate": flips / len(decisive_gold) if decisive_gold else None,
        },
        "rationale_hallucination": {"status": "requires_manual_audit", "rate": None},
        "limitations": [
            "Accuracy_all counts API, invalid-output and budget failures as incorrect.",
            "Tags designate challenge subsets supplied with the input, not independently detected model errors.",
            "Relation correctness and ENTAILED precision do not establish material-reason correctness or RP.",
            "Frozen development cases do not establish hidden-test generalization.",
        ],
    }


def _token_usage(usage):
    """Retain token accounting only, excluding arbitrary echoed server fields."""
    result = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if type(value) is int and value >= 0:
            result[key] = value
    for key in ("prompt_tokens_details", "completion_tokens_details"):
        detail = usage.get(key)
        if isinstance(detail, dict):
            result[key] = {name: value for name, value in detail.items()
                           if isinstance(name, str) and name.endswith("_tokens")
                           and type(value) is int and value >= 0}
    return result


def run_cases(cases, client, stream, budget, *, pacer=None, transport=None,
              progress=print, clock=time.monotonic):
    """Run each case once at completion level; shared budget also bounds retries."""
    records = []
    exhausted = False
    for index, case in enumerate(cases, 1):
        messages = build_messages(case["claim"], case["evidence"], case.get("candidate_response"))
        row = {"id": case["id"], "row_id": case["row_id"],
               "gold_relation": case["gold_relation"], "tags": _tags(case),
               "prompt_sha256": _hash(_json(messages).encode()),
               "status": "budget_exceeded", "relation": None, "rationale": None,
               "evidence_ids": [], "raw_response": None, "usage": {},
               "response_model": None, "error_category": None}
        started, requests_before = clock(), budget.requests
        try:
            if exhausted or budget.requests >= budget.max_requests:
                raise BudgetExceeded("Run budget exhausted")
            budget.remaining_seconds()
            if pacer is not None:
                pacer.wait(budget)
            if transport is not None:
                transport.case_id = case["id"]
            completion = client.complete(messages, schema=None, budget=budget)
            row["raw_response"] = completion.content
            # Preserve only standard usage counts and nested token accounting;
            # client completion excludes HTTP metadata and transport secrets.
            row["usage"] = _token_usage(completion.usage)
            row["response_model"] = completion.model
            verification = parse_verification(completion.content, case["evidence"])
            row.update(status="valid", relation=verification.verdict,
                       rationale=verification.rationale, evidence_ids=list(verification.evidence_ids))
        except VerificationError as error:
            row.update(status="invalid_output", error_category=error.category)
        except BudgetExceeded:
            exhausted = True
            row.update(status="budget_exceeded", error_category="budget_exceeded")
        except ChatClientError as error:
            row.update(status="api_error", error_category=error.category)
            try:
                budget.remaining_seconds()
            except BudgetExceeded:
                exhausted = True
                row.update(status="budget_exceeded", error_category="budget_exceeded")
        row["http_attempts_reserved"] = budget.requests - requests_before
        row["elapsed_seconds"] = max(0, clock() - started)
        _write_line(stream, row)
        records.append(row)
        progress(_json({"completed": index, "total": len(cases), "id": case["id"],
                        "status": row["status"], "relation": row["relation"]}), flush=True)
    report = summarize(records)
    report["budget"] = budget.summary()
    return report


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--provider", choices=("groq", "openrouter", "gemini"),
                        help="Bind endpoint and credentials explicitly; omitted preserves the configured profile")
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--max-output-tokens", type=int, default=2048)
    parser.add_argument("--interval-seconds", type=float, default=20)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--max-requests", type=int, default=60)
    parser.add_argument("--seconds", type=float, default=1800)
    parser.add_argument("--max-input-chars", type=int, default=8_000_000)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("Use a new, nonexisting output directory")
    if not args.env_file.is_file():
        parser.error("Explicit env file must exist")
    if args.input.resolve() == args.env_file.resolve():
        parser.error("Input and credentials must be different files")
    try:
        cases, input_hash = load_cases(args.input)
        load_env_file(args.env_file)
        initial = ClientConfig.from_env()
        if args.provider is None:
            config = replace(initial, model=args.model)
        else:
            selected_url = initial.base_url if args.provider == "groq" else None
            config = provider_config(initial, args.provider, model=args.model,
                                     base_url=selected_url)
        config = replace(config, max_output_tokens=args.max_output_tokens,
                         max_retries=args.retries, strict_schema=False)
        budget = RunBudget(max_requests=args.max_requests,
                           max_input_chars=args.max_input_chars, seconds=args.seconds)
        pacer = Pacer(args.interval_seconds)
        ChatClient(config).validate_configuration()
    except (ValueError, ChatClientError, OSError):
        parser.error("Invalid input, environment, or bounded-run configuration")
    package = Path(__import__("guardian_truth").__file__).parent
    sources = {str(p.relative_to(package.parent)): _hash(p.read_bytes())
               for p in sorted(package.glob("*.py"))}
    sources["scripts/benchmark_claim_relations.py"] = _hash(Path(__file__).read_bytes())
    configuration = {
        "provider": args.provider or "configured", "model": config.model,
        "base_url": config.base_url,
        "input_sha256": input_hash, "case_count": len(cases),
        "system_prompt_sha256": _hash(INSTRUCTION.encode()),
        "case_prompt_sha256": {case["id"]: _hash(_json(build_messages(
            case["claim"], case["evidence"], case.get("candidate_response"))).encode()) for case in cases},
        "source_sha256": sources,
        "request_settings": {"temperature": 0, "max_completion_tokens": config.max_output_tokens,
                             "response_format": {"type": "json_object"}, "strict_schema": False,
                             "schema": None, "stream": False,
                             "reasoning_settings": "native provider/model defaults; no overrides sent"},
        "interval_seconds": args.interval_seconds, "pacing_basis": "every HTTP attempt start, including retries",
        "max_retries": config.max_retries, "timeout_seconds": config.timeout_seconds,
        "max_requests": args.max_requests, "max_input_chars": args.max_input_chars,
        "seconds": args.seconds, "budget_time_basis": "wall clock, including pacing and retries",
        "scope": "claim/evidence shadow verification only; no production labels changed",
    }
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir / "configuration.json").open("x", encoding="utf-8") as stream:
        json.dump(configuration, stream, indent=2, ensure_ascii=True, allow_nan=False)
    # Raw frozen input and credentials are never copied into run artifacts.
    with (args.output_dir / "attempts.jsonl").open("x", encoding="utf-8") as attempts, \
         (args.output_dir / "calls.jsonl").open("x", encoding="utf-8") as calls:
        audited = AuditedTransport(attempts, pacer, budget)

        def bounded_sleep(delay):
            until = time.monotonic() + delay
            while True:
                remaining = until - time.monotonic()
                if remaining <= 0:
                    return
                time.sleep(min(1.0, remaining, budget.remaining_seconds()))

        client = ChatClient(config, transport=audited, sleep=bounded_sleep)
        report = run_cases(cases, client, calls, budget, transport=audited)
    report["input_sha256"] = input_hash
    report["model"] = config.model
    with (args.output_dir / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=True, allow_nan=False)
    print(_json({"output_dir": str(args.output_dir), "accuracy_all": report["accuracy_all"],
                 "accuracy_valid": report["accuracy_valid"], "valid": report["valid"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

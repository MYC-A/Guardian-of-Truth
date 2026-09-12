"""Predeclared provider reliability gate for Cycle 2.

Transport, schema validity, and semantic correctness are separate outcomes.
The gate deliberately uses zero automatic retries so one logical case equals
one auditable HTTP attempt and intermediate 429s cannot disappear in a retry.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Callable, Iterable, Mapping, Protocol

from guardian_truth.llm_client import ChatClientError, Completion


OUTCOMES = {
    "TRANSPORT_ERROR",
    "SCHEMA_ERROR",
    "SEMANTIC_WRONG",
    "SEMANTIC_CORRECT",
}


class CompletionClient(Protocol):
    def complete(
        self,
        messages: list[dict],
        *,
        schema: dict | None = None,
        reasoning_effort: str | None = None,
    ) -> Completion: ...


@dataclass(frozen=True)
class GateCase:
    id: str
    family: str
    prompt: str
    expected_answer: str


@dataclass(frozen=True)
class GateRequest:
    temperature: int
    reasoning_effort: str
    timeout_seconds: float
    max_output_tokens: int
    max_retries: int
    interval_seconds: float


@dataclass(frozen=True)
class GateThresholds:
    minimum_attempts: int
    minimum_transport_success_ratio: float
    minimum_schema_valid_ratio: float
    maximum_rate_limit_ratio: float
    maximum_timeout_ratio: float
    maximum_server_error_ratio: float
    maximum_consecutive_rate_limits: int


@dataclass(frozen=True)
class GateContract:
    schema_version: str
    digest: str
    request: GateRequest
    thresholds: GateThresholds
    answer_vocabulary: tuple[str, ...]
    cases: tuple[GateCase, ...]


def _strict_json(text: str) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_: str):
        raise ValueError("non-finite JSON number")

    return json.loads(text, object_pairs_hook=unique, parse_constant=reject_constant)


def _exact_keys(value: Any, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


def _ratio(value: Any, *, lower: float = 0.0, upper: float = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid ratio")
    result = float(value)
    if not math.isfinite(result) or not lower <= result <= upper:
        raise ValueError("invalid ratio")
    return result


def load_gate_contract(path: Path) -> GateContract:
    raw = path.read_bytes()
    payload = _strict_json(raw.decode("utf-8"))
    expected = {
        "schema_version", "frozen_before_policy_benchmark", "purpose",
        "request", "thresholds", "answer_vocabulary", "cases",
    }
    if not _exact_keys(payload, expected):
        raise ValueError("invalid gate contract envelope")
    if payload["schema_version"] != "guardian-cycle2-model-gate-v1":
        raise ValueError("unsupported gate contract")
    if payload["frozen_before_policy_benchmark"] is not True:
        raise ValueError("gate must be frozen before the policy benchmark")

    request = payload["request"]
    request_keys = {
        "temperature", "reasoning_effort", "timeout_seconds",
        "max_output_tokens", "max_retries", "interval_seconds",
    }
    if not _exact_keys(request, request_keys):
        raise ValueError("invalid request contract")
    if request["temperature"] != 0 or request["reasoning_effort"] not in {"low", "medium", "high"}:
        raise ValueError("invalid fixed generation settings")
    if type(request["max_output_tokens"]) is not int or request["max_output_tokens"] <= 0:
        raise ValueError("invalid max output tokens")
    if request["max_retries"] != 0:
        raise ValueError("Cycle 2 gate requires zero hidden retries")
    timeout = _ratio(request["timeout_seconds"], lower=0.001, upper=300.0)
    interval = _ratio(request["interval_seconds"], lower=0.0, upper=300.0)

    thresholds = payload["thresholds"]
    threshold_keys = {
        "minimum_attempts", "minimum_transport_success_ratio",
        "minimum_schema_valid_ratio", "maximum_rate_limit_ratio",
        "maximum_timeout_ratio", "maximum_server_error_ratio",
        "maximum_consecutive_rate_limits",
    }
    if not _exact_keys(thresholds, threshold_keys):
        raise ValueError("invalid threshold contract")
    if type(thresholds["minimum_attempts"]) is not int or not 12 <= thresholds["minimum_attempts"] <= 20:
        raise ValueError("gate requires 12-20 attempts")
    if (type(thresholds["maximum_consecutive_rate_limits"]) is not int
            or thresholds["maximum_consecutive_rate_limits"] < 0):
        raise ValueError("invalid consecutive-rate-limit threshold")

    vocabulary = payload["answer_vocabulary"]
    if (not isinstance(vocabulary, list) or len(vocabulary) != len(set(vocabulary))
            or any(not isinstance(item, str) or not item for item in vocabulary)):
        raise ValueError("invalid answer vocabulary")
    rows = payload["cases"]
    if not isinstance(rows, list) or not 12 <= len(rows) <= 20:
        raise ValueError("gate requires 12-20 cases")
    cases = []
    for row in rows:
        if (not _exact_keys(row, {"id", "family", "prompt", "expected_answer"})
                or any(not isinstance(row[key], str) or not row[key].strip()
                       for key in ("id", "family", "prompt", "expected_answer"))
                or row["expected_answer"] not in vocabulary):
            raise ValueError("invalid gate case")
        cases.append(GateCase(**row))
    if len({case.id for case in cases}) != len(cases) or len({case.family for case in cases}) < 4:
        raise ValueError("gate cases require unique ids and multiple task families")
    if len(cases) < thresholds["minimum_attempts"]:
        raise ValueError("contract has fewer cases than required attempts")

    return GateContract(
        schema_version=payload["schema_version"],
        digest=hashlib.sha256(raw).hexdigest(),
        request=GateRequest(
            temperature=0,
            reasoning_effort=request["reasoning_effort"],
            timeout_seconds=timeout,
            max_output_tokens=request["max_output_tokens"],
            max_retries=0,
            interval_seconds=interval,
        ),
        thresholds=GateThresholds(
            minimum_attempts=thresholds["minimum_attempts"],
            minimum_transport_success_ratio=_ratio(thresholds["minimum_transport_success_ratio"]),
            minimum_schema_valid_ratio=_ratio(thresholds["minimum_schema_valid_ratio"]),
            maximum_rate_limit_ratio=_ratio(thresholds["maximum_rate_limit_ratio"]),
            maximum_timeout_ratio=_ratio(thresholds["maximum_timeout_ratio"]),
            maximum_server_error_ratio=_ratio(thresholds["maximum_server_error_ratio"]),
            maximum_consecutive_rate_limits=thresholds["maximum_consecutive_rate_limits"],
        ),
        answer_vocabulary=tuple(vocabulary),
        cases=tuple(cases),
    )


def response_schema(contract: GateContract) -> dict:
    """One identical schema is used for every provider, model, and case."""
    return {
        "type": "object",
        "properties": {
            "case_id": {"type": "string", "enum": [case.id for case in contract.cases]},
            "answer": {"type": "string", "enum": list(contract.answer_vocabulary)},
        },
        "required": ["case_id", "answer"],
        "additionalProperties": False,
    }


def _parse_answer(content: str, contract: GateContract) -> tuple[str, str]:
    value = _strict_json(content)
    if not _exact_keys(value, {"case_id", "answer"}):
        raise ValueError("invalid gate answer fields")
    if (not isinstance(value["case_id"], str) or not isinstance(value["answer"], str)
            or value["case_id"] not in {case.id for case in contract.cases}
            or value["answer"] not in contract.answer_vocabulary):
        raise ValueError("invalid gate answer values")
    return value["case_id"], value["answer"]


def _percentile(values: Iterable[float], probability: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    index = max(0, math.ceil(probability * len(ordered)) - 1)
    return round(ordered[index], 3)


def _safe_usage(usage: Mapping[str, Any]) -> dict[str, int]:
    result = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if type(value) is int and value >= 0:
            result[key] = value
    details = usage.get("completion_tokens_details")
    if isinstance(details, Mapping):
        value = details.get("reasoning_tokens")
        if type(value) is int and value >= 0:
            result["reasoning_tokens"] = value
    return result


def _max_consecutive(categories: list[str | None], target: str) -> int:
    longest = current = 0
    for category in categories:
        current = current + 1 if category == target else 0
        longest = max(longest, current)
    return longest


def evaluate_candidate(
    client: CompletionClient,
    contract: GateContract,
    *,
    provider: str,
    requested_model: str,
    credential_status: str,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Run all predeclared cases; no expected answer enters a model prompt."""
    schema = response_schema(contract)
    records = []
    last_start: float | None = None
    error_categories: list[str | None] = []
    for case in contract.cases:
        now = clock()
        if last_start is not None:
            remaining = contract.request.interval_seconds - (now - last_start)
            if remaining > 0:
                sleep(remaining)
        started = clock()
        last_start = started
        completion = None
        category = None
        try:
            completion = client.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "Classify one Guardian semantic micro-task. Return only the required "
                            "structured object. Do not infer an unobserved effect or completion."
                        ),
                    },
                    {"role": "user", "content": f"CASE_ID: {case.id}\nTASK: {case.prompt}"},
                ],
                schema=schema,
                reasoning_effort=contract.request.reasoning_effort,
            )
        except ChatClientError as error:
            category = error.category
        except Exception:
            category = "client_contract"
        elapsed_ms = round(max(0.0, clock() - started) * 1000.0, 3)
        error_categories.append(category)
        row = {
            "case_id": case.id,
            "family": case.family,
            "outcome": "TRANSPORT_ERROR",
            "transport_status": "error",
            "schema_status": "not_evaluated",
            "semantic_status": "not_evaluated",
            "error_category": category,
            "latency_ms": elapsed_ms,
            "served_model": None,
            "usage": {},
        }
        if completion is not None:
            row.update({
                "transport_status": "success",
                "schema_status": "invalid",
                "error_category": None,
                "served_model": completion.model,
                "usage": _safe_usage(completion.usage),
            })
            try:
                case_id, answer = _parse_answer(completion.content, contract)
                correct = case_id == case.id and answer == case.expected_answer
                row.update({
                    "outcome": "SEMANTIC_CORRECT" if correct else "SEMANTIC_WRONG",
                    "schema_status": "valid",
                    "semantic_status": "correct" if correct else "wrong",
                    "answer": answer,
                })
            except (ValueError, TypeError, UnicodeError, RecursionError):
                row.update({"outcome": "SCHEMA_ERROR", "semantic_status": "not_evaluated"})
        if row["outcome"] not in OUTCOMES:
            raise AssertionError("unreachable invalid gate outcome")
        records.append(row)

    attempts = len(records)
    transport_success = sum(row["transport_status"] == "success" for row in records)
    schema_valid = sum(row["schema_status"] == "valid" for row in records)
    semantic_correct = sum(row["semantic_status"] == "correct" for row in records)
    rate_limits = sum(category == "rate_limit" for category in error_categories)
    server_errors = sum(category == "server" for category in error_categories)
    timeouts = sum(category == "timeout" for category in error_categories)
    served = sorted({row["served_model"] for row in records if row["served_model"]})
    latencies = [row["latency_ms"] for row in records]
    thresholds = contract.thresholds
    checks = {
        "attempts": attempts >= thresholds.minimum_attempts,
        "transport_reliability": transport_success / attempts >= thresholds.minimum_transport_success_ratio,
        "schema_reliability": schema_valid / attempts >= thresholds.minimum_schema_valid_ratio,
        "rate_limit_ratio": rate_limits / attempts <= thresholds.maximum_rate_limit_ratio,
        "timeout_ratio": timeouts / attempts <= thresholds.maximum_timeout_ratio,
        "server_error_ratio": server_errors / attempts <= thresholds.maximum_server_error_ratio,
        "consecutive_rate_limits": _max_consecutive(error_categories, "rate_limit")
        <= thresholds.maximum_consecutive_rate_limits,
    }
    passed = all(checks.values())
    return {
        "provider": provider,
        "requested_model": requested_model,
        "served_model": served[0] if len(served) == 1 else "MIXED" if served else None,
        "served_models": served,
        "credential_status": credential_status,
        "attempts": attempts,
        "transport_success": transport_success,
        "schema_valid": schema_valid,
        "semantic_correct": semantic_correct,
        "429_count": rate_limits,
        "5xx_count": server_errors,
        "timeout_count": timeouts,
        "latency_p50": _percentile(latencies, 0.50),
        "latency_p95": _percentile(latencies, 0.95),
        "reliability": round(schema_valid / attempts, 6),
        "conditional_semantic_quality": round(semantic_correct / schema_valid, 6) if schema_valid else None,
        "strict_operational_yield": round(semantic_correct / attempts, 6),
        "admission_checks": checks,
        "admitted": passed,
        "cases": records,
    }


def blocked_candidate(
    *, provider: str, requested_model: str, credential_status: str, reason: str,
) -> dict:
    """Represent local configuration failure without pretending calls were attempted."""
    return {
        "provider": provider,
        "requested_model": requested_model,
        "served_model": None,
        "served_models": [],
        "credential_status": credential_status,
        "attempts": 0,
        "transport_success": 0,
        "schema_valid": 0,
        "semantic_correct": 0,
        "429_count": 0,
        "5xx_count": 0,
        "timeout_count": 0,
        "latency_p50": None,
        "latency_p95": None,
        "reliability": None,
        "conditional_semantic_quality": None,
        "strict_operational_yield": None,
        "admission_checks": {},
        "admitted": False,
        "configuration_status": reason,
        "cases": [],
    }


def build_gate_report(contract: GateContract, candidates: Iterable[dict]) -> dict:
    candidates = list(candidates)
    admitted = [f"{row['provider']}={row['requested_model']}" for row in candidates if row["admitted"]]
    return {
        "schema_version": "guardian-cycle2-model-gate-result-v1",
        "gate_contract_sha256": contract.digest,
        "thresholds_frozen_before_benchmark": True,
        "request_settings": {
            "temperature": contract.request.temperature,
            "reasoning_effort": contract.request.reasoning_effort,
            "timeout_seconds": contract.request.timeout_seconds,
            "max_output_tokens": contract.request.max_output_tokens,
            "max_retries": contract.request.max_retries,
            "interval_seconds": contract.request.interval_seconds,
            "response_schema_sha256": hashlib.sha256(
                json.dumps(response_schema(contract), sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        },
        "thresholds": {
            key: value for key, value in vars(contract.thresholds).items()
        },
        "status": "PASSED" if admitted else "EVALUATION_BLOCKED_BY_PROVIDER",
        "policy_benchmark_permitted": bool(admitted),
        "admitted_candidates": admitted,
        "candidates": candidates,
    }

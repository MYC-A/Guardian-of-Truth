"""Transport-verified raw ToolResult observations, without semantic promotion.

An observed JSON scalar is source data, not a WorldFact. In particular a
failure response, an unrecognised field, or an unreviewed tool description
cannot establish a business predicate or an effect strength.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from guardian_truth.step2.result_types import classify_payload, json_path_get, scalar_to_json
from guardian_truth.step2.trusted import producer_scope
from guardian_truth.step2.verifier import TrajectoryCase


_KEY = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")


@dataclass(frozen=True)
class SourceObservation:
    producer: str
    call_id: str
    call_index: int
    result_index: int
    json_path: str
    value_json: str
    result_type: str

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _scalars(node, path: str, depth: int = 0):
    if depth > 8:
        return
    if isinstance(node, dict):
        for key, value in node.items():
            # The shared JSON-path reader does not support escaped keys.
            if isinstance(key, str) and _KEY.fullmatch(key):
                yield from _scalars(value, path + "." + key, depth + 1)
    elif isinstance(node, list):
        for index, value in enumerate(node[:256]):
            yield from _scalars(value, path + f"[{index}]", depth + 1)
    elif path != "$":
        rendered = scalar_to_json(node)
        if rendered is not None:
            yield path, rendered


def collect_observations(case: TrajectoryCase) -> tuple[tuple[SourceObservation, ...], tuple[str, ...]]:
    """Collect exact scalar fields only from uniquely paired call/results.

    The catalog slot is fingerprinted by ``producer_scope``. No entity,
    predicate, authority, or successful outcome is inferred here.
    """
    observations: list[SourceObservation] = []
    issues: list[str] = []
    for result in case.results:
        calls = [c for c in case.calls if c.call_id == result.call_id]
        results = [r for r in case.results if r.call_id == result.call_id]
        if len(calls) != 1 or len(results) != 1:
            issues.append(f"{result.call_id}@{result.index}:pair_not_unique")
            continue
        call = calls[0]
        if (call.index >= result.index or call.tool != result.tool
                or call.actor != "assistant" or result.actor != "tool"):
            issues.append(f"{result.call_id}@{result.index}:transport_mismatch")
            continue
        producer = producer_scope(case, call.tool)
        if producer is None:
            issues.append(f"{result.call_id}@{result.index}:producer_not_unique")
            continue
        result_type = classify_payload(result.payload).value
        for path, value in _scalars(result.payload, "$"):
            actual, present = json_path_get(result.payload, path)
            if not present or scalar_to_json(actual) != value:
                issues.append(f"{result.call_id}@{result.index}:{path}:path_unresolved")
                continue
            observations.append(SourceObservation(producer, call.call_id,
                                                  call.index, result.index,
                                                  path, value, result_type))
    return tuple(observations), tuple(issues)

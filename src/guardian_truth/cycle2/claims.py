"""Frozen response-only claim benchmark and blind extractor scoring."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterable, Mapping, Protocol

from guardian_truth.llm_client import ChatClientError, Completion
from guardian_truth.next.claims import extract_claims_with_coverage
from guardian_truth.parsing import parse_events


KINDS = {
    "ACTION_COMPLETED", "ACTION_FAILED", "STATE", "ATTRIBUTION", "INTENT",
    "REFUSAL", "FACT", "ABSENCE", "PERMISSION", "OTHER_VERIFIABLE",
    "NON_VERIFIABLE",
}
CLAIM_KINDS = KINDS - {"NON_VERIFIABLE"}
KIND_MAP = {
    "action": "ACTION_COMPLETED",
    "state": "STATE",
    "attribution": "ATTRIBUTION",
    "intent": "INTENT",
    "refusal": "REFUSAL",
    "fact": "FACT",
    "absence": "ABSENCE",
}
SOURCES = {"ASSISTANT", "USER", "SYSTEM", "TOOL", "UNSPECIFIED"}
SENTENCE = re.compile(r"[^\n.!?]+(?:[.!?]+|$)")


class CompletionClient(Protocol):
    def complete(self, messages: list[dict], *, schema: dict | None = None,
                 reasoning_effort: str | None = None) -> Completion: ...


@dataclass(frozen=True)
class ClaimArmContract:
    digest: str
    timeout_seconds: float
    max_output_tokens: int
    interval_seconds: float
    reasoning_effort: str
    response_format_mode: str
    arm_order: tuple[str, ...]
    c1_system: str
    c2_system: str


@dataclass(frozen=True)
class ClaimAnnotation:
    id: str
    start: int
    end: int
    text: str
    declarative: bool
    kind: str
    entities: tuple[str, ...]
    times: tuple[str, ...]
    source: str
    unsupported: bool | None


@dataclass(frozen=True)
class ClaimCase:
    id: str
    domain: str
    source_kind: str
    response: str
    annotations: tuple[ClaimAnnotation, ...]


@dataclass(frozen=True)
class ClaimDataset:
    digest: str
    cases_digest: str
    cases: tuple[ClaimCase, ...]


def load_claim_arm_contract(path: Path) -> ClaimArmContract:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    request = value.get("request", {}) if isinstance(value, dict) else {}
    if (not isinstance(value, dict)
            or value.get("schema_version") != "guardian-cycle2-claim-arms-v1"
            or value.get("frozen_before_model_predictions") is not True
            or value.get("arm_order") != ["C1", "C2"]
            or set(value.get("kind_vocabulary", [])) != KINDS
            or set(value.get("source_vocabulary", [])) != SOURCES
            or request.get("temperature") != 0 or request.get("max_retries") != 0
            or request.get("response_format_mode") != "none"):
        raise ValueError("invalid claim arm contract")
    return ClaimArmContract(
        hashlib.sha256(raw).hexdigest(), float(request["timeout_seconds"]),
        int(request["max_output_tokens"]), float(request["interval_seconds"]),
        request["reasoning_effort"], request["response_format_mode"], ("C1", "C2"),
        value["C1_system"], value["C2_system"],
    )


def load_claim_dataset(path: Path) -> ClaimDataset:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    required = {
        "schema_version", "frozen_before_extractor_predictions", "extractor_input",
        "source_columns_read", "external_source_sha256",
        "prompt_trace_tool_label_explanation_read", "annotation_method", "kind_vocabulary",
        "n_external_spans", "n_controlled_spans", "n_spans", "cases_sha256", "cases",
    }
    if (not isinstance(value, dict) or set(value) != required
            or value["schema_version"] != "guardian-cycle2-claim-cases-v1"
            or value["frozen_before_extractor_predictions"] is not True
            or value["extractor_input"] != "candidate_response_only"
            or value["source_columns_read"] != ["id", "response"]
            or value["prompt_trace_tool_label_explanation_read"] is not False
            or set(value["kind_vocabulary"]) != KINDS):
        raise ValueError("invalid frozen claim benchmark envelope")
    rows = value["cases"]
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if digest != value["cases_sha256"]:
        raise ValueError("claim cases hash mismatch")
    cases = []
    span_ids = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "domain", "source_kind", "response", "annotations"}:
            raise ValueError("invalid claim case")
        annotations = []
        for item in row["annotations"]:
            if (not isinstance(item, dict) or set(item) != {
                    "id", "start", "end", "text", "declarative", "kind", "entities",
                    "times", "source", "unsupported",
                } or item["id"] in span_ids or item["kind"] not in KINDS
                    or type(item["declarative"]) is not bool
                    or item["declarative"] != (item["kind"] != "NON_VERIFIABLE")
                    or type(item["start"]) is not int or type(item["end"]) is not int
                    or not 0 <= item["start"] < item["end"] <= len(row["response"])
                    or row["response"][item["start"]:item["end"]] != item["text"]
                    or not isinstance(item["entities"], list) or not isinstance(item["times"], list)
                    or item["unsupported"] not in {True, False, None}):
                raise ValueError("invalid claim annotation")
            span_ids.add(item["id"])
            annotations.append(ClaimAnnotation(
                item["id"], item["start"], item["end"], item["text"], item["declarative"],
                item["kind"], tuple(item["entities"]), tuple(item["times"]), item["source"],
                item["unsupported"],
            ))
        cases.append(ClaimCase(row["id"], row["domain"], row["source_kind"], row["response"],
                               tuple(annotations)))
    n_spans = sum(len(case.annotations) for case in cases)
    if n_spans != value["n_spans"] or not 150 <= n_spans <= 300:
        raise ValueError("invalid claim span count")
    return ClaimDataset(hashlib.sha256(raw).hexdigest(), digest, tuple(cases))


def blind_claim_cases(dataset: ClaimDataset) -> tuple[dict, ...]:
    """The only semantic model input is the candidate response."""
    return tuple({"case_id": case.id, "response": case.response} for case in dataset.cases)


def response_spans(response: str) -> list[dict]:
    """Boundary-only decomposition derived from the response, never from gold."""
    spans = []
    for event in parse_events(response, "response"):
        if event.role != "assistant" or event.kind != "text":
            continue
        for match in SENTENCE.finditer(event.text):
            if not match.group().strip():
                continue
            start, end = event.source.start + match.start(), event.source.start + match.end()
            spans.append({"span_id": f"s{len(spans)}", "start": start, "end": end,
                          "text": response[start:end]})
    return spans


def claim_schema(case_id: str, arm: str, spans: list[dict]) -> dict:
    properties = {
        "kind": {"type": "string", "enum": sorted(KINDS)},
        "entities": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "times": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "source": {"type": "string", "enum": sorted(SOURCES)},
    }
    if arm == "C1":
        properties = {
            "start": {"type": "integer", "minimum": 0},
            "end": {"type": "integer", "minimum": 1},
            **properties,
        }
        required = ["start", "end", "kind", "entities", "times", "source"]
    else:
        properties = {
            "span_id": {"type": "string", "enum": [span["span_id"] for span in spans]},
            **properties,
        }
        required = ["span_id", "kind", "entities", "times", "source"]
    item = {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}
    return {
        "type": "object",
        "properties": {
            "case_id": {"type": "string", "const": case_id},
            "spans": {"type": "array", "items": item},
        },
        "required": ["case_id", "spans"],
        "additionalProperties": False,
    }


def claim_messages(case: Mapping[str, str], arm: str,
                   contract: ClaimArmContract) -> tuple[list[dict], dict, list[dict]]:
    if set(case) != {"case_id", "response"} or arm not in {"C1", "C2"}:
        raise ValueError("invalid blind claim input")
    spans = response_spans(case["response"])
    schema = claim_schema(case["case_id"], arm, spans)
    system = contract.c1_system if arm == "C1" else contract.c2_system
    payload: dict[str, Any] = {"case_id": case["case_id"], "response": case["response"]}
    if arm == "C2":
        payload["span_inventory"] = spans
    prompt = (json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
              + "\nOUTPUT_JSON_SCHEMA: "
              + json.dumps(schema, ensure_ascii=False, separators=(",", ":")))
    return ([{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            schema, spans)


def _strict_object(text: str) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    value = json.loads(text, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite")))
    if not isinstance(value, dict):
        raise ValueError("not an object")
    return value


def _safe_usage(value: Mapping[str, Any]) -> dict[str, int]:
    return {key: item for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if type((item := value.get(key))) is int and item >= 0}


def model_claim_proposal(client: CompletionClient, case: Mapping[str, str], arm: str,
                         contract: ClaimArmContract, *,
                         clock: Callable[[], float] = time.monotonic) -> dict:
    messages, schema, inventory = claim_messages(case, arm, contract)
    started = clock()
    base = {
        "case_id": case["case_id"], "arm": arm, "transport_status": "ERROR",
        "schema_status": "NOT_EVALUATED", "claims": [], "coverage": [],
        "error_category": None, "served_model": None, "usage": {},
        "latency_ms": 0.0, "prompt_visible": False, "history_visible": False,
        "evidence_visible": False, "label_visible": False,
    }
    try:
        completion = client.complete(messages, schema=schema, reasoning_effort=contract.reasoning_effort)
    except ChatClientError as error:
        base.update({"error_category": error.category,
                     "latency_ms": round(max(0.0, clock() - started) * 1000, 3)})
        return base
    base.update({
        "transport_status": "SUCCESS", "schema_status": "INVALID",
        "served_model": completion.model, "usage": _safe_usage(completion.usage),
        "latency_ms": round(max(0.0, clock() - started) * 1000, 3),
    })
    try:
        value = _strict_object(completion.content)
        if set(value) != {"case_id", "spans"} or value["case_id"] != case["case_id"] or not isinstance(value["spans"], list):
            raise ValueError("invalid claim envelope")
        by_span = {span["span_id"]: span for span in inventory}
        normalized = []
        seen = set()
        for item in value["spans"]:
            required = ({"start", "end", "kind", "entities", "times", "source"}
                        if arm == "C1" else {"span_id", "kind", "entities", "times", "source"})
            if not isinstance(item, dict) or set(item) != required:
                raise ValueError("invalid claim span fields")
            if item["kind"] not in KINDS or item["source"] not in SOURCES:
                raise ValueError("claim vocabulary violation")
            if (not isinstance(item["entities"], list) or not isinstance(item["times"], list)
                    or any(not isinstance(text, str) for text in [*item["entities"], *item["times"]])
                    or len(item["entities"]) != len(set(item["entities"]))
                    or len(item["times"]) != len(set(item["times"]))):
                raise ValueError("invalid entity/time arrays")
            if arm == "C1":
                start, end = item["start"], item["end"]
                if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(case["response"]):
                    raise ValueError("invalid response offsets")
                key = (start, end)
            else:
                if item["span_id"] not in by_span:
                    raise ValueError("unknown span id")
                span = by_span[item["span_id"]]
                start, end = span["start"], span["end"]
                key = item["span_id"]
            if key in seen:
                raise ValueError("duplicate span")
            seen.add(key)
            normalized.append({"start": start, "end": end, "kind": item["kind"],
                               "entities": item["entities"], "times": item["times"],
                               "source": item["source"]})
        if arm == "C2" and seen != set(by_span):
            raise ValueError("incomplete C2 span inventory")
        claims = [item for item in normalized if item["kind"] in CLAIM_KINDS]
        coverage = [{"start": item["start"], "end": item["end"],
                     "status": "CLAIM" if item["kind"] in CLAIM_KINDS else "NON_VERIFIABLE"}
                    for item in normalized]
        base.update({"schema_status": "VALID", "claims": claims, "coverage": coverage})
    except (ValueError, TypeError, UnicodeError, RecursionError):
        pass
    return base


def run_model_claim_arms(client: CompletionClient, cases: Iterable[Mapping[str, str]],
                         contract: ClaimArmContract, *, existing: Iterable[dict] = (),
                         checkpoint: Callable[[list[dict]], None] | None = None,
                         clock: Callable[[], float] = time.monotonic,
                         sleep: Callable[[float], None] = time.sleep) -> list[dict]:
    rows = list(existing)
    completed = {(row.get("case_id"), row.get("arm")) for row in rows}
    last_start: float | None = None
    for case in cases:
        for arm in contract.arm_order:
            if (case["case_id"], arm) in completed:
                continue
            now = clock()
            if last_start is not None:
                remaining = contract.interval_seconds - (now - last_start)
                if remaining > 0:
                    sleep(remaining)
            last_start = clock()
            rows.append(model_claim_proposal(client, case, arm, contract, clock=clock))
            completed.add((case["case_id"], arm))
            if checkpoint:
                checkpoint(rows)
    return rows


def c0_proposals(dataset: ClaimDataset) -> list[dict]:
    rows = []
    for case in dataset.cases:
        extraction = extract_claims_with_coverage(case.response)
        claims = []
        for claim in extraction.claims:
            kind = KIND_MAP.get(claim.kind.value)
            if kind is None:
                continue
            claims.append({
                "start": claim.source.start,
                "end": claim.source.end,
                "kind": kind,
                "entities": [f"{key}={value}" for key, value in claim.entities],
                "times": [],
                "source": "ASSISTANT" if claim.subject == "assistant" else "UNSPECIFIED",
            })
        coverage = [{"start": item.span.start, "end": item.span.end, "status": item.status}
                    for item in extraction.coverage]
        rows.append({
            "case_id": case.id, "arm": "C0", "transport_status": "NOT_APPLICABLE",
            "schema_status": "VALID", "claims": claims, "coverage": coverage,
            "prompt_visible": False, "history_visible": False, "evidence_visible": False,
            "label_visible": False,
        })
    return rows


def _canonical_entities(values: Iterable[str]) -> set[str]:
    return {re.sub(r"[^a-zа-яё0-9]", "", value.lower()) for value in values}


def score_claim_proposals(dataset: ClaimDataset, proposals: Iterable[dict], arm: str) -> dict:
    by_id = {case.id: case for case in dataset.cases}
    rows = [row for row in proposals if row.get("arm") == arm]
    if len(rows) != len(by_id) or {row.get("case_id") for row in rows} != set(by_id):
        raise ValueError("claim proposals incomplete")
    gold_claims = predicted_claims = matched = kind_correct = 0
    entity_total = entity_correct = time_total = time_correct = source_total = source_correct = 0
    declarative = covered_declarative = unsupported_total = unsupported_found = 0
    schema_valid = transport_success = 0
    per_case = []
    for row in rows:
        case = by_id[row["case_id"]]
        valid = row.get("schema_status") == "VALID"
        schema_valid += valid
        transport_success += row.get("transport_status") in {"SUCCESS", "NOT_APPLICABLE"}
        gold = {(item.start, item.end): item for item in case.annotations if item.kind in CLAIM_KINDS}
        predicted = {(item["start"], item["end"]): item for item in row.get("claims", [])} if valid else {}
        gold_claims += len(gold)
        predicted_claims += len(predicted)
        common = set(gold) & set(predicted)
        matched += len(common)
        for key in common:
            expected, actual = gold[key], predicted[key]
            kind_correct += actual.get("kind") == expected.kind
            if expected.entities:
                entity_total += 1
                entity_correct += _canonical_entities(actual.get("entities", [])) == _canonical_entities(expected.entities)
            if expected.times:
                time_total += 1
                time_correct += set(actual.get("times", [])) == set(expected.times)
            source_total += 1
            source_correct += actual.get("source") == expected.source
        coverage = {(item["start"], item["end"]): item.get("status") for item in row.get("coverage", [])}
        case_decl = [item for item in case.annotations if item.declarative]
        declarative += len(case_decl)
        covered_declarative += sum(coverage.get((item.start, item.end)) in {"CLAIM", "NON_VERIFIABLE", "UNKNOWN"}
                                    for item in case_decl)
        unsupported = [item for item in case.annotations if item.unsupported is True]
        unsupported_total += len(unsupported)
        unsupported_found += sum((item.start, item.end) in predicted for item in unsupported)
        per_case.append({"case_id": case.id, "gold_claims": len(gold),
                         "predicted_claims": len(predicted), "matched_spans": len(common)})
    return {
        "cases": len(rows), "transport_success": transport_success, "schema_valid": schema_valid,
        "reliability": schema_valid / len(rows) if rows else None,
        "gold_claim_spans": gold_claims, "predicted_claim_spans": predicted_claims,
        "span_recall": matched / gold_claims if gold_claims else None,
        "span_precision": matched / predicted_claims if predicted_claims else None,
        "kind_accuracy": kind_correct / matched if matched else None,
        "entity_accuracy": entity_correct / entity_total if entity_total else None,
        "time_accuracy": time_correct / time_total if time_total else None,
        "source_accuracy": source_correct / source_total if source_total else None,
        "declarative_coverage": covered_declarative / declarative if declarative else None,
        "unsupported_claim_recall": unsupported_found / unsupported_total if unsupported_total else None,
        "unsupported_claims": unsupported_total,
        "per_case": per_case,
    }


def build_c0_claim_report(dataset: ClaimDataset) -> dict[str, Any]:
    proposals = c0_proposals(dataset)
    canonical = json.dumps(proposals, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "guardian-cycle2-claim-results-v1",
        "status": "C0_COMPLETE_MODEL_ARMS_PENDING",
        "benchmark_sha256": dataset.digest,
        "cases_sha256": dataset.cases_digest,
        "extractor_input": "candidate_response_only",
        "gold_visible_to_proposal_stage": False,
        "proposal_freeze_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "arms": {"C0": score_claim_proposals(dataset, proposals, "C0")},
        "unavailable_arms": {"C1": "NOT_RUN", "C2": "NOT_RUN"},
        "proposals": proposals,
    }


def build_claim_report(dataset: ClaimDataset, contract: ClaimArmContract,
                       model_proposals: Iterable[dict]) -> dict[str, Any]:
    proposals = [*c0_proposals(dataset), *model_proposals]
    expected = {(case.id, arm) for case in dataset.cases for arm in ("C0", "C1", "C2")}
    actual = {(row.get("case_id"), row.get("arm")) for row in proposals}
    if actual != expected or len(proposals) != len(expected):
        raise ValueError("claim proposals incomplete or duplicated")
    canonical = json.dumps(proposals, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "guardian-cycle2-claim-results-v1",
        "status": "COMPLETED",
        "benchmark_sha256": dataset.digest,
        "cases_sha256": dataset.cases_digest,
        "claim_arm_contract_sha256": contract.digest,
        "extractor_input": "candidate_response_only",
        "gold_visible_to_proposal_stage": False,
        "proposals_frozen_before_gold_join": True,
        "proposal_freeze_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "arms": {arm: score_claim_proposals(dataset, proposals, arm) for arm in ("C0", "C1", "C2")},
        "proposals": proposals,
    }

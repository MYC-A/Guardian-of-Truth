"""Frozen response-only claim benchmark and blind extractor scoring."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from guardian_truth.next.claims import extract_claims_with_coverage


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

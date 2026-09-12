"""Gold-isolated Policy Semantics V2 arm runner and paired scoring."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import random
import time
from typing import Any, Callable, Iterable, Mapping, Protocol

from guardian_truth.next.policy import compile_policy
from guardian_truth.llm_client import ChatClientError, Completion

from .policy_semantics import (
    PolicyCase,
    PolicyDataset,
    STRUCTURAL_FIELDS,
    compile_typed_structure,
    score_policy_candidate,
    score_policy_program,
    validate_program,
)


class CompletionClient(Protocol):
    def complete(self, messages: list[dict], *, schema: dict | None = None,
                 reasoning_effort: str | None = None) -> Completion: ...


@dataclass(frozen=True)
class PolicyArmContract:
    digest: str
    timeout_seconds: float
    max_output_tokens: int
    max_retries: int
    interval_seconds: float
    response_format_mode: str
    reasoning_effort: str
    arm_order: tuple[str, ...]
    p1_system: str
    p2_system: str
    minimum_paired_cases: int
    bootstrap_resamples: int
    bootstrap_seed: int


@dataclass(frozen=True)
class BlindPolicyCase:
    id: str
    family: str
    variant: str
    policy: str
    atom_catalog: tuple[str, ...]


def load_policy_arm_contract(path) -> PolicyArmContract:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if (not isinstance(value, dict)
            or value.get("schema_version") != "guardian-cycle2-policy-arms-v1"
            or value.get("frozen_before_model_predictions") is not True
            or value.get("arm_order") != ["P1", "P2"]):
        raise ValueError("invalid policy arm contract")
    request = value.get("request")
    comparison = value.get("comparison")
    if not isinstance(request, dict) or not isinstance(comparison, dict):
        raise ValueError("invalid policy arm settings")
    if (request.get("temperature") != 0 or request.get("max_retries") != 0
            or request.get("response_format_mode") != "none"
            or request.get("reasoning_effort") not in {"low", "medium", "high"}):
        raise ValueError("unsafe policy arm request settings")
    return PolicyArmContract(
        digest=hashlib.sha256(raw).hexdigest(),
        timeout_seconds=float(request["timeout_seconds"]),
        max_output_tokens=int(request["max_output_tokens"]),
        max_retries=0,
        interval_seconds=float(request["interval_seconds"]),
        response_format_mode="none",
        reasoning_effort=request["reasoning_effort"],
        arm_order=("P1", "P2"),
        p1_system=value["P1_system"],
        p2_system=value["P2_system"],
        minimum_paired_cases=int(comparison["minimum_paired_cases_for_conclusion"]),
        bootstrap_resamples=int(comparison["bootstrap_resamples"]),
        bootstrap_seed=int(comparison["bootstrap_seed"]),
    )


def blind_policy_cases(dataset: PolicyDataset) -> tuple[BlindPolicyCase, ...]:
    """Return a proposal-safe view with no gold structure, program, or worlds."""
    return tuple(BlindPolicyCase(
        case.id, case.family, case.variant, case.policy, case.atom_catalog,
    ) for case in dataset.cases)


def _strict_object(text: str) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(text, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite")))
    if not isinstance(value, dict):
        raise ValueError("response is not an object")
    return value


def _literal_schema(case: BlindPolicyCase) -> dict:
    literals = list(case.atom_catalog) + ["!" + atom for atom in case.atom_catalog]
    return {"type": "string", "enum": literals}


def p1_schema(case: BlindPolicyCase) -> dict:
    clause = {"type": "array", "items": _literal_schema(case), "minItems": 1,
              "uniqueItems": True}
    return {
        "type": "object",
        "properties": {
            "case_id": {"type": "string", "const": case.id},
            "violation_clauses": {"type": "array", "items": clause},
            "permission_clauses": {"type": "array", "items": clause},
        },
        "required": ["case_id", "violation_clauses", "permission_clauses"],
        "additionalProperties": False,
    }


def p2_schema(case: BlindPolicyCase) -> dict:
    clause = {"type": "array", "items": _literal_schema(case), "minItems": 1,
              "uniqueItems": True}
    literal_array = {"type": "array", "items": _literal_schema(case), "uniqueItems": True}
    properties = {
        "case_id": {"type": "string", "const": case.id},
        "modality": {"type": "string", "enum": ["PROHIBITION", "REQUIREMENT", "PERMISSION"]},
        "actor": {"type": "string", "enum": ["assistant", "agent", "human_reviewer", "verifier"]},
        "regulated_kind": {"type": "string", "enum": ["ACTION", "INFORMATION", "STATE"]},
        "facet": {"type": "string", "minLength": 1},
        "target_clauses": {"type": "array", "items": clause, "minItems": 1},
        "relation": {"type": "string", "enum": [
            "UNCONDITIONAL", "IF", "ONLY_IF", "IF_AND_ONLY_IF", "UNLESS", "DURING", "AND_NOT_EACH",
        ]},
        "condition_literals": literal_array,
        "exception_literals": literal_array,
        "temporal": {"type": "string", "enum": ["NONE", "BEFORE", "AFTER", "DURING"]},
        "identity": {"type": "string", "enum": [
            "ANY", "SAME_USER", "DIFFERENT_USER", "SAME_ORDER", "SAME_ORDER_OWNER",
            "SAME_RESERVATION", "SAME_ALERT", "SAME_TURN", "DIFFERENT_ENTITY_TYPES",
            "SOURCE_TO_RECIPIENT",
        ]},
        "provenance": {"type": "string", "enum": [
            "ANY", "USER", "USER_OR_TOOL", "TOOL_RESULT", "FRESH_TOOL_READ", "CONFIRMED_EFFECT",
        ]},
        "quantification": {"type": "string", "enum": [
            "ANY", "ALL", "COUNT", "AT_MOST_1_PER_TURN", "AT_MOST_3", "AT_LEAST_2_OF_4", "NOT_BOTH",
        ]},
    }
    return {
        "type": "object", "properties": properties,
        "required": list(properties), "additionalProperties": False,
    }


def arm_messages(case: BlindPolicyCase, arm: str, contract: PolicyArmContract) -> tuple[list[dict], dict]:
    schema = p1_schema(case) if arm == "P1" else p2_schema(case)
    system = contract.p1_system if arm == "P1" else contract.p2_system
    prompt = (
        f"CASE_ID: {case.id}\nPOLICY: {case.policy}\nATOMS: "
        + json.dumps(list(case.atom_catalog), ensure_ascii=False)
        + "\nOUTPUT_JSON_SCHEMA: "
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    )
    return ([{"role": "system", "content": system}, {"role": "user", "content": prompt}], schema)


def _safe_usage(value: Mapping[str, Any]) -> dict[str, int]:
    return {key: item for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if type((item := value.get(key))) is int and item >= 0}


def _validate_p2_structure(structure: Mapping[str, Any], case: BlindPolicyCase) -> None:
    schema = p2_schema(case)["properties"]
    for key in ("modality", "actor", "regulated_kind", "relation", "temporal",
                "identity", "provenance", "quantification"):
        if structure.get(key) not in schema[key]["enum"]:
            raise ValueError("typed scalar outside vocabulary")
    if not isinstance(structure.get("facet"), str) or not structure["facet"]:
        raise ValueError("invalid facet")
    allowed = frozenset(case.atom_catalog) | frozenset("!" + atom for atom in case.atom_catalog)
    targets = structure.get("target_clauses")
    if (not isinstance(targets, list) or not targets
            or any(not isinstance(clause, list) or not clause or len(clause) != len(set(clause))
                   or any(literal not in allowed for literal in clause) for clause in targets)):
        raise ValueError("invalid typed targets")
    for key in ("condition_literals", "exception_literals"):
        literals = structure.get(key)
        if (not isinstance(literals, list) or len(literals) != len(set(literals))
                or any(literal not in allowed for literal in literals)):
            raise ValueError("invalid typed literals")


def model_policy_proposal(client: CompletionClient, case: BlindPolicyCase, arm: str,
                          contract: PolicyArmContract, *,
                          clock: Callable[[], float] = time.monotonic) -> dict:
    if arm not in {"P1", "P2"}:
        raise ValueError("unsupported policy arm")
    messages, schema = arm_messages(case, arm, contract)
    started = clock()
    try:
        completion = client.complete(messages, schema=schema, reasoning_effort=contract.reasoning_effort)
    except ChatClientError as error:
        return {
            "case_id": case.id, "arm": arm, "transport_status": "ERROR",
            "schema_status": "NOT_EVALUATED", "semantic_status": "PENDING_GOLD_JOIN",
            "representation_status": "NOT_EVALUATED", "error_category": error.category,
            "prediction": None, "source_coverage": None, "served_model": None,
            "latency_ms": round(max(0.0, clock() - started) * 1000, 3), "usage": {},
        }
    row = {
        "case_id": case.id, "arm": arm, "transport_status": "SUCCESS",
        "schema_status": "INVALID", "semantic_status": "PENDING_GOLD_JOIN",
        "representation_status": "NOT_EVALUATED", "error_category": None,
        "prediction": None, "source_coverage": 1.0, "served_model": completion.model,
        "latency_ms": round(max(0.0, clock() - started) * 1000, 3),
        "usage": _safe_usage(completion.usage),
    }
    try:
        value = _strict_object(completion.content)
        if arm == "P1":
            if set(value) != {"case_id", "violation_clauses", "permission_clauses"}:
                raise ValueError("invalid P1 fields")
            if value["case_id"] != case.id:
                raise ValueError("wrong case id")
            program = {key: value[key] for key in ("violation_clauses", "permission_clauses")}
            validate_program(program, frozenset(case.atom_catalog))
            row.update({"schema_status": "VALID", "representation_status": "SUPPORTED",
                        "prediction": {"structure": None, "program": program}})
        else:
            if set(value) != {"case_id", *STRUCTURAL_FIELDS} or value["case_id"] != case.id:
                raise ValueError("invalid P2 fields")
            structure = {key: value[key] for key in STRUCTURAL_FIELDS}
            _validate_p2_structure(structure, case)
            try:
                program = compile_typed_structure(structure)
                validate_program(program, frozenset(case.atom_catalog))
                representation = "SUPPORTED"
            except ValueError:
                # The typed object is still a valid model output; compilation support
                # is a semantic/representation result, not a transport failure.
                program = None
                representation = "UNSUPPORTED"
            row.update({"schema_status": "VALID", "representation_status": representation,
                        "prediction": {"structure": structure, "program": program}})
    except (ValueError, TypeError, UnicodeError, RecursionError):
        pass
    return row


def run_model_policy_arms(client: CompletionClient, cases: Iterable[BlindPolicyCase],
                          contract: PolicyArmContract, *, existing: Iterable[dict] = (),
                          checkpoint: Callable[[list[dict]], None] | None = None,
                          clock: Callable[[], float] = time.monotonic,
                          sleep: Callable[[float], None] = time.sleep) -> list[dict]:
    """Run one request at a time and support auditable proposal-only resume."""
    rows = list(existing)
    completed = {(row.get("case_id"), row.get("arm")) for row in rows}
    last_start: float | None = None
    for case in cases:
        for arm in contract.arm_order:
            if (case.id, arm) in completed:
                continue
            now = clock()
            if last_start is not None:
                remaining = contract.interval_seconds - (now - last_start)
                if remaining > 0:
                    sleep(remaining)
            last_start = clock()
            rows.append(model_policy_proposal(client, case, arm, contract, clock=clock))
            completed.add((case.id, arm))
            if checkpoint is not None:
                checkpoint(rows)
    return rows


def _empty_structure(*, facet: str, target: str, relation: str = "UNCONDITIONAL",
                     identity: str = "ANY", quantification: str = "ANY") -> dict:
    return {
        "modality": "PROHIBITION",
        "actor": "assistant",
        "regulated_kind": "ACTION",
        "facet": facet,
        "target_clauses": [[target]],
        "relation": relation,
        "condition_literals": [],
        "exception_literals": [],
        "temporal": "NONE",
        "identity": identity,
        "provenance": "ANY",
        "quantification": quantification,
    }


def p0_proposal(case: BlindPolicyCase) -> dict:
    """Apply the unchanged exact compiler; no benchmark string list is used."""
    prefix = "⟦SYSTEM⟧\n<policy>"
    bundle = compile_policy(prefix + case.policy + "</policy>", arm="P0_CYCLE2")
    predicates = {rule.predicate for rule in bundle.rules}
    prediction = None
    if predicates == {"max_tool_calls"} and "turn:tool_call_count_gt_1" in case.atom_catalog:
        prediction = {
            "structure": _empty_structure(
                facet="tool_call_count", target="turn:tool_call_count_gt_1",
                quantification="AT_MOST_1_PER_TURN",
            ),
            "program": {
                "violation_clauses": [["turn:tool_call_count_gt_1"]],
                "permission_clauses": [],
            },
        }
    elif predicates == {"text_xor_tool_call"} and {
        "turn:has_message", "turn:has_tool_call",
    } <= set(case.atom_catalog):
        structure = _empty_structure(
            facet="turn_channels", target="turn:has_message",
            relation="AND_NOT_EACH", identity="SAME_TURN", quantification="NOT_BOTH",
        )
        structure["target_clauses"] = [["turn:has_message", "turn:has_tool_call"]]
        prediction = {
            "structure": structure,
            "program": {
                "violation_clauses": [["turn:has_message", "turn:has_tool_call"]],
                "permission_clauses": [],
            },
        }
    covered = sum(item.span.end - item.span.start for item in bundle.coverage
                  if item.status == "RULE")
    return {
        "case_id": case.id,
        "arm": "P0",
        "transport_status": "NOT_APPLICABLE",
        "schema_status": "VALID",
        "semantic_status": "PENDING_GOLD_JOIN",
        "representation_status": "SUPPORTED" if prediction else "UNSUPPORTED",
        "error_category": None,
        "prediction": prediction,
        "source_coverage": min(1.0, covered / len(case.policy)) if case.policy else 0.0,
        "served_model": None,
        "latency_ms": 0.0,
        "usage": {},
    }


def freeze_proposals(rows: Iterable[dict]) -> tuple[list[dict], str]:
    rows = list(rows)
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return rows, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def score_proposals(rows: Iterable[dict], dataset: PolicyDataset) -> list[dict]:
    """Gold can enter only here, after proposal bytes have been frozen."""
    gold: Mapping[str, PolicyCase] = {case.id: case for case in dataset.cases}
    scored = []
    seen = set()
    for row in rows:
        key = (row["case_id"], row["arm"])
        if key in seen or row["case_id"] not in gold:
            raise ValueError("duplicate or unknown policy proposal")
        seen.add(key)
        item = {
            "case_id": row["case_id"],
            "arm": row["arm"],
            "family": gold[row["case_id"]].family,
            "variant": gold[row["case_id"]].variant,
            "transport_status": row["transport_status"],
            "schema_status": row["schema_status"],
            "representation_status": row["representation_status"],
            "semantic_outcome": "NOT_EVALUATED",
            "behavioral_semantic_correct": None,
            "behavioral_accuracy": None,
            "structural_accuracy": None,
            "exact_representation": None,
        }
        prediction = row.get("prediction")
        if (row["schema_status"] == "VALID" and prediction is not None
                and prediction.get("program") is not None):
            if prediction.get("structure") is None:
                score = score_policy_program(gold[row["case_id"]], prediction["program"])
            else:
                score = score_policy_candidate(
                    gold[row["case_id"]], prediction["structure"], prediction["program"],
                )
            item.update({
                "semantic_outcome": (
                    "SEMANTIC_CORRECT" if score["behavioral_semantic_correct"]
                    else "SEMANTIC_WRONG"
                ),
                "behavioral_semantic_correct": score["behavioral_semantic_correct"],
                "behavioral_accuracy": score["behavioral_accuracy"],
                "structural_accuracy": score["structural_accuracy"],
                "structural_fields": score["structural_fields"],
                "exact_representation": score["exact_representation"],
            })
        elif row["schema_status"] == "VALID":
            item.update({
                "semantic_outcome": "SEMANTIC_WRONG",
                "behavioral_semantic_correct": False,
                "behavioral_accuracy": 0.0,
                "structural_accuracy": None,
                "exact_representation": False,
            })
        scored.append(item)
    return scored


def summarize_arm(proposals: Iterable[dict], scores: Iterable[dict], arm: str) -> dict:
    proposals = [row for row in proposals if row["arm"] == arm]
    scores = [row for row in scores if row["arm"] == arm]
    attempted = len(proposals)
    transport = sum(row["transport_status"] in {"SUCCESS", "NOT_APPLICABLE"} for row in proposals)
    valid = sum(row["schema_status"] == "VALID" for row in proposals)
    correct = sum(row["behavioral_semantic_correct"] is True for row in scores)
    evaluated = [row for row in scores if row["behavioral_semantic_correct"] is not None]
    structural = [row for row in evaluated if row["structural_accuracy"] is not None]
    return {
        "attempted": attempted,
        "transport_success": transport,
        "schema_valid": valid,
        "semantic_correct": correct,
        "reliability": valid / attempted if attempted else None,
        "conditional_semantic_quality": correct / valid if valid else None,
        "strict_operational_yield": correct / attempted if attempted else None,
        "mean_behavioral_accuracy": (
            sum(row["behavioral_accuracy"] for row in evaluated) / len(evaluated)
            if evaluated else None
        ),
        "mean_structural_accuracy": (
            sum(row["structural_accuracy"] for row in structural) / len(structural)
            if structural else None
        ),
        "exact_representation_accuracy": (
            sum(row["exact_representation"] is True for row in evaluated) / len(evaluated)
            if evaluated else None
        ),
        "supported_representations": sum(row["representation_status"] == "SUPPORTED" for row in proposals),
    }


def _bootstrap_difference(pairs: list[tuple[bool, bool]], *, resamples: int,
                          seed: int) -> list[float] | None:
    if not pairs:
        return None
    randomizer = random.Random(seed)
    n = len(pairs)
    values = []
    for _ in range(resamples):
        sample = [pairs[randomizer.randrange(n)] for _ in range(n)]
        values.append(sum(int(p2) - int(p1) for p1, p2 in sample) / n)
    values.sort()
    return [values[int(0.025 * (resamples - 1))], values[int(0.975 * (resamples - 1))]]


def paired_p1_p2(scores: Iterable[dict], *, minimum_cases: int,
                 bootstrap_resamples: int, bootstrap_seed: int) -> dict:
    by_key = {(row["case_id"], row["arm"]): row for row in scores}
    ids = sorted({case_id for case_id, _ in by_key})
    valid_p1 = {case_id for case_id in ids
                if by_key.get((case_id, "P1"), {}).get("behavioral_semantic_correct") is not None}
    valid_p2 = {case_id for case_id in ids
                if by_key.get((case_id, "P2"), {}).get("behavioral_semantic_correct") is not None}
    both = sorted(valid_p1 & valid_p2)
    pairs = [(bool(by_key[(case_id, "P1")]["behavioral_semantic_correct"]),
              bool(by_key[(case_id, "P2")]["behavioral_semantic_correct"])) for case_id in both]
    p1_only = sum(p1 and not p2 for p1, p2 in pairs)
    p2_only = sum(p2 and not p1 for p1, p2 in pairs)
    discordant = p1_only + p2_only
    if discordant:
        tail = sum(math.comb(discordant, k) for k in range(min(p1_only, p2_only) + 1)) / (2 ** discordant)
        mcnemar_p = min(1.0, 2 * tail)
    else:
        mcnemar_p = 1.0
    enough = len(both) >= minimum_cases
    return {
        "status": "ESTIMATED" if enough else "NO_CONCLUSION",
        "reason": None if enough else "paired_sample_below_predeclared_minimum",
        "n_total": len(ids),
        "n_P1_valid": len(valid_p1),
        "n_P2_valid": len(valid_p2),
        "n_both_valid": len(both),
        "P1_accuracy_on_both": sum(p1 for p1, _ in pairs) / len(pairs) if pairs else None,
        "P2_accuracy_on_both": sum(p2 for _, p2 in pairs) / len(pairs) if pairs else None,
        "P2_minus_P1": sum(int(p2) - int(p1) for p1, p2 in pairs) / len(pairs) if pairs else None,
        "P2_minus_P1_bootstrap_95ci": _bootstrap_difference(
            pairs, resamples=bootstrap_resamples, seed=bootstrap_seed,
        ) if enough else None,
        "P1_only_correct": p1_only,
        "P2_only_correct": p2_only,
        "both_correct": sum(p1 and p2 for p1, p2 in pairs),
        "both_wrong": sum(not p1 and not p2 for p1, p2 in pairs),
        "mcnemar_exact_two_sided_p": mcnemar_p if enough else None,
    }


def build_policy_report(dataset: PolicyDataset, gate_report: Mapping[str, Any],
                        contract: PolicyArmContract, model_proposals: Iterable[dict]) -> dict:
    if gate_report.get("policy_benchmark_permitted") is not True:
        raise ValueError("model policy report requires a passed gate")
    p0 = [p0_proposal(case) for case in blind_policy_cases(dataset)]
    proposals, proposal_hash = freeze_proposals([*p0, *model_proposals])
    expected = {(case.id, arm) for case in dataset.cases for arm in ("P0", "P1", "P2")}
    actual = {(row.get("case_id"), row.get("arm")) for row in proposals}
    if actual != expected or len(proposals) != len(expected):
        raise ValueError("policy proposals are incomplete or duplicated")
    scores = score_proposals(proposals, dataset)
    paired = paired_p1_p2(
        scores,
        minimum_cases=contract.minimum_paired_cases,
        bootstrap_resamples=contract.bootstrap_resamples,
        bootstrap_seed=contract.bootstrap_seed,
    )
    return {
        "schema_version": "guardian-cycle2-policy-results-v1",
        "status": "COMPLETED",
        "benchmark_sha256": dataset.digest,
        "cases_sha256": dataset.cases_digest,
        "gate_contract_sha256": gate_report.get("gate_contract_sha256"),
        "policy_arm_contract_sha256": contract.digest,
        "model_gate_status": gate_report.get("status"),
        "gold_visible_to_proposal_stage": False,
        "proposal_freeze_sha256": proposal_hash,
        "proposals_frozen_before_gold_join": True,
        "arms": {arm: summarize_arm(proposals, scores, arm) for arm in ("P0", "P1", "P2")},
        "unavailable_arms": {
            "P3": "NOT_ESTABLISHED_NO_SECOND_STRONGER_GATE_ADMITTED_MODEL",
            "P4": "NOT_RUN_PENDING_P2_ANALYSIS",
        },
        "paired_p1_p2": paired,
        "proposals": proposals,
        "scores": scores,
    }


def build_blocked_policy_report(dataset: PolicyDataset, gate_report: Mapping[str, Any]) -> dict:
    if gate_report.get("policy_benchmark_permitted") is not False:
        raise ValueError("blocked report requires a failed model gate")
    blind = blind_policy_cases(dataset)
    proposals, proposal_hash = freeze_proposals(p0_proposal(case) for case in blind)
    scores = score_proposals(proposals, dataset)
    return {
        "schema_version": "guardian-cycle2-policy-results-v1",
        "status": "EVALUATION_BLOCKED_BY_PROVIDER",
        "benchmark_sha256": dataset.digest,
        "cases_sha256": dataset.cases_digest,
        "gate_contract_sha256": gate_report.get("gate_contract_sha256"),
        "model_gate_status": gate_report.get("status"),
        "gold_visible_to_proposal_stage": False,
        "proposal_freeze_sha256": proposal_hash,
        "proposals_frozen_before_gold_join": True,
        "arms": {"P0": summarize_arm(proposals, scores, "P0")},
        "unavailable_arms": {
            "P1": "NOT_ESTABLISHED_PROVIDER_GATE_BLOCKED",
            "P2": "NOT_ESTABLISHED_PROVIDER_GATE_BLOCKED",
            "P3": "NOT_ESTABLISHED_PROVIDER_GATE_BLOCKED",
            "P4": "NOT_RUN_REQUIRES_VALID_P2",
        },
        "paired_p1_p2": {
            "status": "NO_CONCLUSION",
            "reason": "provider_reliability_gate_not_passed",
            "n_total": len(dataset.cases),
            "n_P1_valid": 0,
            "n_P2_valid": 0,
            "n_both_valid": 0,
            "P1_accuracy_on_both": None,
            "P2_accuracy_on_both": None,
            "P1_only_correct": 0,
            "P2_only_correct": 0,
            "both_correct": 0,
            "both_wrong": 0,
        },
        "proposals": proposals,
        "scores": scores,
    }

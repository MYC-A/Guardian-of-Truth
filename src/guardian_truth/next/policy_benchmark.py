"""Frozen, gold-isolated policy-semantics benchmark harness.

Proposal generation accepts only :class:`BlindPolicySuite`.  Gold metadata is
held in a distinct type and can enter only :func:`score_policy_proposals`, after
all proposal records already exist.  The module performs no network setup and
does not claim that an arm passed merely because transport or schema validation
succeeded.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from guardian_truth.language import BudgetExceeded, RunBudget
from guardian_truth.llm_client import ChatClientError
from guardian_truth.typed_formalization import EFFECTS, FEATURES, RELATIONS
from guardian_truth.typed_translation import (
    FREE_SCHEMA,
    build_free_messages,
    normalize_operator,
    parse_free_formalization,
)

from .model_tasks import POLICY_MEANING_SCHEMA, propose_policy_meaning
from .policy import compile_policy
from .records import PolicyMeaning, PolicyModality, SemanticUncertainty


class PolicyArm(str, Enum):
    P0 = "P0"
    P1_DIRECT = "P1"
    P2_TYPED = "P2"
    P3_REASONING = "P3"


@dataclass(frozen=True)
class BlindPolicyCase:
    case_id: str
    row_id: str
    rule: str
    source_start: int
    source_end: int
    source_sha256: str


@dataclass(frozen=True)
class BlindPolicySuite:
    benchmark_sha256: str
    cases: tuple[BlindPolicyCase, ...]
    data_role: str


@dataclass(frozen=True)
class GoldPolicyCase:
    case_id: str
    supported_by_fragment: bool
    relations: tuple[str, ...]
    effects: tuple[str, ...]
    operators: tuple[str, ...]
    features: tuple[tuple[str, str | bool], ...]
    critical_requirements: tuple[str, ...]


@dataclass(frozen=True)
class PolicyGoldSet:
    benchmark_sha256: str
    cases: tuple[GoldPolicyCase, ...]


def _exact_keys(value: Any, expected: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == expected


def _string_tuple(value: Any, *, allowed: set[str] | None = None) -> tuple[str, ...]:
    if (not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value)
            or len(set(value)) != len(value)):
        raise ValueError("invalid frozen benchmark string list")
    if allowed is not None and any(item not in allowed for item in value):
        raise ValueError("invalid frozen benchmark enum")
    return tuple(value)


def load_frozen_policy_benchmark(path: str | Path) -> tuple[BlindPolicySuite, PolicyGoldSet]:
    """Load and split the frozen file into proposal-safe and scoring-only views."""
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, TypeError):
        raise ValueError("invalid frozen policy benchmark") from None
    if (not isinstance(payload, dict) or payload.get("schema_version") != 1
            or not isinstance(payload.get("data_role"), str)
            or not isinstance(payload.get("cases"), list) or not payload["cases"]):
        raise ValueError("invalid frozen policy benchmark envelope")
    blind, gold, ids = [], [], set()
    feature_names = set(FEATURES) | {"negation", "exception"}
    feature_values = {name: set(values) for name, values in FEATURES.items()}
    for item in payload["cases"]:
        if not _exact_keys(item, {"case_id", "row_id", "source", "rule", "gold"}):
            raise ValueError("invalid frozen benchmark case")
        case_id, row_id, rule = item["case_id"], item["row_id"], item["rule"]
        if (not all(isinstance(value, str) and value for value in (case_id, row_id, rule))
                or case_id in ids):
            raise ValueError("invalid or duplicate frozen benchmark case id")
        ids.add(case_id)
        source = item["source"]
        if (not _exact_keys(source, {"document", "role", "start", "end", "sha256"})
                or source["document"] != "prompt" or source["role"] != "SYSTEM"
                or type(source["start"]) is not int or type(source["end"]) is not int
                or not 0 <= source["start"] < source["end"]
                or source["end"] - source["start"] != len(rule)
                or source["sha256"] != hashlib.sha256(rule.encode("utf-8")).hexdigest()):
            raise ValueError("invalid frozen benchmark source identity")
        blind.append(BlindPolicyCase(
            case_id, row_id, rule, source["start"], source["end"], source["sha256"],
        ))
        target = item["gold"]
        if not _exact_keys(target, {
            "supported_by_fragment", "relations", "effects", "operators", "features",
            "critical_requirements",
        }) or type(target["supported_by_fragment"]) is not bool:
            raise ValueError("invalid frozen benchmark gold")
        features = target["features"]
        if (not isinstance(features, dict) or set(features) != feature_names
                or any(features[name] not in feature_values[name] for name in FEATURES)
                or type(features["negation"]) is not bool or type(features["exception"]) is not bool):
            raise ValueError("invalid frozen benchmark features")
        gold.append(GoldPolicyCase(
            case_id=case_id,
            supported_by_fragment=target["supported_by_fragment"],
            relations=_string_tuple(target["relations"], allowed=set(RELATIONS)),
            effects=_string_tuple(target["effects"], allowed=set(EFFECTS)),
            operators=_string_tuple(target["operators"]),
            features=tuple(sorted(features.items())),
            critical_requirements=_string_tuple(target["critical_requirements"]),
        ))
    return (
        BlindPolicySuite(digest, tuple(blind), payload["data_role"]),
        PolicyGoldSet(digest, tuple(gold)),
    )


@dataclass(frozen=True)
class ArmBudget:
    max_requests_per_case: int = 1
    max_input_chars_per_case: int = 200_000
    seconds_per_case: float = 120.0
    max_output_tokens: int = 4096

    def __post_init__(self):
        if (type(self.max_requests_per_case) is not int or self.max_requests_per_case < 1
                or type(self.max_input_chars_per_case) is not int or self.max_input_chars_per_case < 1
                or type(self.seconds_per_case) not in (int, float) or self.seconds_per_case <= 0
                or type(self.max_output_tokens) is not int or self.max_output_tokens < 1):
            raise ValueError("invalid arm budget")


@dataclass(frozen=True)
class ArmSpec:
    arm: PolicyArm
    budget: ArmBudget
    reasoning_effort: str | None = None

    def __post_init__(self):
        if self.reasoning_effort not in (None, "low", "medium", "high"):
            raise ValueError("invalid arm reasoning effort")
        if self.arm is PolicyArm.P0 and self.reasoning_effort is not None:
            raise ValueError("P0 has no model reasoning effort")


def default_arm_specs(*, budget: ArmBudget | None = None) -> tuple[ArmSpec, ...]:
    """P1/P2 use exactly the same request, time, input, output and reasoning budgets."""
    shared = budget or ArmBudget()
    return (
        ArmSpec(PolicyArm.P0, shared),
        ArmSpec(PolicyArm.P1_DIRECT, shared, "low"),
        ArmSpec(PolicyArm.P2_TYPED, shared, "low"),
        ArmSpec(PolicyArm.P3_REASONING, shared, "high"),
    )


class TransportStatus(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    SUCCESS = "success"
    API_ERROR = "api_error"
    BUDGET_EXCEEDED = "budget_exceeded"


class ValidationStatus(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True)
class SemanticPrediction:
    status: str
    relations: tuple[str, ...]
    effects: tuple[str, ...]
    operators: tuple[str, ...]
    features: tuple[tuple[str, str | bool | None], ...]


@dataclass(frozen=True)
class PolicyProposalRecord:
    case_id: str
    arm: PolicyArm
    transport_status: TransportStatus
    validation_status: ValidationStatus
    error_category: str | None
    prediction: SemanticPrediction | None
    source_coverage: float
    unknown_source_coverage: float
    usage: tuple[tuple[str, int], ...]
    returned_model: str | None
    proposal_sha256: str | None


@dataclass(frozen=True)
class PolicyProposalRun:
    benchmark_sha256: str
    records: tuple[PolicyProposalRecord, ...]
    budgets: tuple[tuple[str, ArmBudget], ...]
    p1_p2_equal_budget: bool
    gold_visible_to_proposal_stage: bool = False


def _union_coverage(spans: Iterable[tuple[int, int]], length: int) -> float:
    points: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if not 0 <= start < end <= length:
            raise ValueError("proposal source span outside isolated rule")
        if points and start <= points[-1][1]:
            points[-1] = (points[-1][0], max(points[-1][1], end))
        else:
            points.append((start, end))
    return sum(end - start for start, end in points) / length if length else 0.0


def _features(**values: str | bool | None) -> tuple[tuple[str, str | bool | None], ...]:
    names = (*FEATURES.keys(), "negation", "exception")
    return tuple((name, values.get(name)) for name in names)


def _p0_proposal(case: BlindPolicyCase) -> tuple[SemanticPrediction, float]:
    prefix = "⟦SYSTEM⟧\n<policy>"
    bundle = compile_policy(prefix + case.rule + "</policy>", arm="P0-benchmark")
    predicates = {item.predicate for item in bundle.rules}
    operators = set()
    if "max_tool_calls" in predicates:
        operators.update(("COUNT", "LE"))
    if "text_xor_tool_call" in predicates:
        operators.update(("AND", "NOT"))
    effects = ("REQUIRED",) if predicates & {"max_tool_calls", "text_xor_tool_call"} else ()
    if predicates == {"current_date"}:
        effects = ("ASSERTED",)
    spans = []
    for item in bundle.rules:
        start, end = item.source.start - len(prefix), item.source.end - len(prefix)
        if 0 <= start < end <= len(case.rule):
            spans.append((start, end))
    prediction = SemanticPrediction(
        status="SUPPORTED" if bundle.rules else "UNSUPPORTED",
        relations=("UNCONDITIONAL",) if bundle.rules else (),
        effects=effects,
        operators=tuple(sorted(operators)),
        features=_features(negation=True if "text_xor_tool_call" in predicates else None),
    )
    return prediction, _union_coverage(spans, len(case.rule))


def _p1_prediction(raw: str, rule: str) -> tuple[SemanticPrediction, float]:
    parsed = parse_free_formalization(raw, rule)
    if parsed.status == "UNSUPPORTED":
        return SemanticPrediction("UNSUPPORTED", (), (), (), _features()), 0.0
    operators = tuple(sorted({
        normalized for item in parsed.operators
        if (normalized := normalize_operator(item)) is not None
    }))
    supplied = dict(parsed.features)
    prediction = SemanticPrediction(
        status="SUPPORTED",
        relations=(parsed.relation,),
        effects=(parsed.effect,),
        operators=operators,
        features=_features(
            **supplied,
            negation=("NOT" in operators or parsed.effect == "PROHIBITED"),
            # The P1 wire schema has no exception slot; do not infer one from prose.
            exception=None,
        ),
    )
    spans = []
    for quote in parsed.support_quotes:
        start = rule.index(quote)
        spans.append((start, start + len(quote)))
    return prediction, _union_coverage(spans, len(rule))


def _collapse(values: Iterable[str]) -> str | None:
    values = set(values)
    return next(iter(values)) if len(values) == 1 else None


def _typed_prediction(meanings: tuple[PolicyMeaning, ...], unknown_spans, rule: str) -> tuple[SemanticPrediction, float, float]:
    certain = tuple(item for item in meanings if item.uncertainty is SemanticUncertainty.CERTAIN)
    uncertain = len(certain) != len(meanings) or bool(unknown_spans)
    if not meanings:
        status = "UNSUPPORTED"
    elif not certain:
        status = "UNSUPPORTED"
    elif uncertain:
        status = "PARTIAL"
    else:
        status = "SUPPORTED"
    modality_map = {
        PolicyModality.PERMISSION: "MAY",
        PolicyModality.PROHIBITION: "MUST",
        PolicyModality.REQUIREMENT: "MUST",
        PolicyModality.DEFINITION: "NONE",
        PolicyModality.CONTEXT: "NONE",
    }
    effect_map = {
        PolicyModality.PERMISSION: "PERMITTED",
        PolicyModality.PROHIBITION: "PROHIBITED",
        PolicyModality.REQUIREMENT: "REQUIRED",
        PolicyModality.DEFINITION: "ASSERTED",
        PolicyModality.CONTEXT: "ASSERTED",
    }
    quantifier_map = {
        "all": "ALL", "any": "ANY", "none": "NONE", "unspecified": "NONE",
    }
    operators = set()
    for meaning in certain:
        relation = meaning.temporal.relation
        if relation in {"before", "after"}:
            operators.add(relation.upper())
        if len(meaning.conditions) > 1:
            operators.add("AND")
        if meaning.modality is PolicyModality.PROHIBITION:
            operators.add("NOT")
        if meaning.identity_constraints:
            operators.add("SAME_ENTITY")
        quantifier = meaning.quantification.kind
        if quantifier in {"exactly", "at_least", "at_most"}:
            operators.add("COUNT")
            operators.add({"exactly": "EQ", "at_least": "GE", "at_most": "LE"}[quantifier])
    complete = bool(certain) and not uncertain
    features = _features(
        modality=_collapse(modality_map[item.modality] for item in certain),
        quantifier=_collapse(quantifier_map.get(item.quantification.kind, "ALL") for item in certain),
        # Current PolicyMeaning does not encode causal strength or condition direction.
        causality=None,
        strength=None,
        condition=("NONE" if complete and all(not item.conditions for item in certain) else None),
        negation=(any(item.modality is PolicyModality.PROHIBITION for item in certain) if complete else None),
        exception=(any(item.exceptions for item in certain) if complete else None),
    )
    source_spans = ((item.provenance.source.start, item.provenance.source.end) for item in meanings)
    unknown = ((item.start, item.end) for item in unknown_spans)
    return (
        SemanticPrediction(
            status=status,
            relations=(),
            effects=tuple(sorted({effect_map[item.modality] for item in certain})),
            operators=tuple(sorted(operators)),
            features=features,
        ),
        _union_coverage(source_spans, len(rule)),
        _union_coverage(unknown, len(rule)),
    )


def _validate_specs_and_clients(specs: tuple[ArmSpec, ...], clients: Mapping[PolicyArm, Any]) -> bool:
    if len({spec.arm for spec in specs}) != len(specs):
        raise ValueError("duplicate policy arm specification")
    by_arm = {spec.arm: spec for spec in specs}
    both = PolicyArm.P1_DIRECT in by_arm and PolicyArm.P2_TYPED in by_arm
    if both and (by_arm[PolicyArm.P1_DIRECT].budget != by_arm[PolicyArm.P2_TYPED].budget
                 or by_arm[PolicyArm.P1_DIRECT].reasoning_effort
                 != by_arm[PolicyArm.P2_TYPED].reasoning_effort):
        raise ValueError("P1 and P2 must use equal budgets and reasoning effort")
    for spec in specs:
        if spec.arm is PolicyArm.P0:
            continue
        if spec.arm not in clients:
            raise ValueError(f"missing client for {spec.arm.value}")
        configured = getattr(getattr(clients[spec.arm], "config", None), "max_output_tokens", None)
        if configured is not None and configured != spec.budget.max_output_tokens:
            raise ValueError("client output limit differs from frozen arm budget")
    return both


def run_policy_proposals(
    suite: BlindPolicySuite,
    *,
    clients: Mapping[PolicyArm, Any] | None = None,
    specs: Iterable[ArmSpec] | None = None,
) -> PolicyProposalRun:
    """Run blind proposal arms.  This signature cannot accept gold metadata."""
    clients = clients or {}
    specs = tuple(specs or default_arm_specs())
    equal = _validate_specs_and_clients(specs, clients)
    budgets = {
        spec.arm: RunBudget(
            spec.budget.max_requests_per_case * len(suite.cases),
            spec.budget.max_input_chars_per_case * len(suite.cases),
            spec.budget.seconds_per_case * len(suite.cases),
        ) for spec in specs if spec.arm is not PolicyArm.P0
    }
    records = []
    for case in suite.cases:
        for spec in specs:
            if spec.arm is PolicyArm.P0:
                prediction, coverage = _p0_proposal(case)
                records.append(PolicyProposalRecord(
                    case.case_id, spec.arm, TransportStatus.NOT_APPLICABLE,
                    ValidationStatus.VALID, None, prediction, coverage, 0.0, (), None, None,
                ))
                continue
            client = clients[spec.arm]
            transport = TransportStatus.SUCCESS
            validation = ValidationStatus.INVALID
            error, prediction, coverage, unknown_coverage = None, None, 0.0, 0.0
            usage, model, raw_hash = (), None, None
            try:
                if spec.arm is PolicyArm.P1_DIRECT:
                    completion = client.complete(
                        build_free_messages(case.rule), schema=FREE_SCHEMA,
                        budget=budgets[spec.arm], reasoning_effort=spec.reasoning_effort,
                    )
                    raw_hash = hashlib.sha256(completion.content.encode("utf-8")).hexdigest()
                    usage = tuple(sorted(
                        (key, value) for key, value in completion.usage.items()
                        if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                        and type(value) is int and value >= 0
                    ))
                    model = completion.model
                    prediction, coverage = _p1_prediction(completion.content, case.rule)
                    validation = ValidationStatus.VALID
                else:
                    proposal = propose_policy_meaning(
                        client, case.rule, budget=budgets[spec.arm],
                        reasoning_effort=spec.reasoning_effort,
                    )
                    prediction, coverage, unknown_coverage = _typed_prediction(
                        proposal.meanings, proposal.unknown_spans, case.rule,
                    )
                    usage = tuple(sorted(
                        (key, value) for key, value in proposal.usage.items()
                        if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                        and type(value) is int and value >= 0
                    ))
                    model = proposal.returned_model
                    validation = ValidationStatus.VALID
            except (ValueError, TypeError, RecursionError) as exc:
                error = type(exc).__name__
            except BudgetExceeded:
                transport, error = TransportStatus.BUDGET_EXCEEDED, "budget_exceeded"
            except ChatClientError as exc:
                transport, error = TransportStatus.API_ERROR, exc.category
            records.append(PolicyProposalRecord(
                case.case_id, spec.arm, transport, validation, error, prediction,
                coverage, unknown_coverage, usage, model, raw_hash,
            ))
    return PolicyProposalRun(
        suite.benchmark_sha256,
        tuple(records),
        tuple((spec.arm.value, spec.budget) for spec in specs),
        p1_p2_equal_budget=equal,
    )


def _set_score(actual: tuple[str, ...], expected: tuple[str, ...]) -> tuple[float, float]:
    actual_set, expected_set = set(actual), set(expected)
    overlap = len(actual_set & expected_set)
    precision = overlap / len(actual_set) if actual_set else (1.0 if not expected_set else 0.0)
    recall = overlap / len(expected_set) if expected_set else (1.0 if not actual_set else 0.0)
    return precision, recall


@dataclass(frozen=True)
class ScoredPolicyRecord:
    case_id: str
    arm: PolicyArm
    transport_status: TransportStatus
    validation_status: ValidationStatus
    prediction_status: str | None
    source_coverage: float
    unknown_source_coverage: float
    semantic_correct: bool
    feature_coverage: float
    feature_accuracy_covered: float | None
    feature_accuracy_all: float
    relation_precision: float
    relation_recall: float
    effect_precision: float
    effect_recall: float
    operator_precision: float
    operator_recall: float


@dataclass(frozen=True)
class PolicyBenchmarkReport:
    benchmark_sha256: str
    records: tuple[ScoredPolicyRecord, ...]
    by_arm: tuple[tuple[str, tuple[tuple[str, float | int | None], ...]], ...]
    scoring_stage: str = "GOLD_APPLIED_AFTER_PROPOSAL_FREEZE"


def score_policy_proposals(run: PolicyProposalRun, gold_set: PolicyGoldSet) -> PolicyBenchmarkReport:
    """Join frozen proposals to gold and report transport, validation and semantics separately."""
    if run.benchmark_sha256 != gold_set.benchmark_sha256:
        raise ValueError("proposal and gold benchmark identities differ")
    gold = {item.case_id: item for item in gold_set.cases}
    if len(gold) != len(gold_set.cases):
        raise ValueError("duplicate scoring case id")
    scored = []
    for record in run.records:
        if record.case_id not in gold:
            raise ValueError("proposal case is absent from gold set")
        target = gold[record.case_id]
        prediction = record.prediction
        predicted_features = dict(prediction.features) if prediction else {}
        target_features = dict(target.features)
        covered = [name for name in target_features if predicted_features.get(name) is not None]
        correct = [name for name in covered if predicted_features[name] == target_features[name]]
        relation = _set_score(prediction.relations if prediction else (), target.relations)
        effect = _set_score(prediction.effects if prediction else (), target.effects)
        operator = _set_score(prediction.operators if prediction else (), target.operators)
        if target.supported_by_fragment:
            semantic = bool(
                prediction and prediction.status == "SUPPORTED"
                and relation == (1.0, 1.0) and effect == (1.0, 1.0)
                and operator == (1.0, 1.0) and len(correct) == len(target_features)
            )
        else:
            semantic = bool(prediction and prediction.status == "UNSUPPORTED")
        scored.append(ScoredPolicyRecord(
            case_id=record.case_id, arm=record.arm,
            transport_status=record.transport_status,
            validation_status=record.validation_status,
            prediction_status=prediction.status if prediction else None,
            source_coverage=record.source_coverage,
            unknown_source_coverage=record.unknown_source_coverage,
            semantic_correct=semantic,
            feature_coverage=len(covered) / len(target_features),
            feature_accuracy_covered=len(correct) / len(covered) if covered else None,
            feature_accuracy_all=len(correct) / len(target_features),
            relation_precision=relation[0], relation_recall=relation[1],
            effect_precision=effect[0], effect_recall=effect[1],
            operator_precision=operator[0], operator_recall=operator[1],
        ))
    groups = defaultdict(list)
    for item in scored:
        groups[item.arm.value].append(item)
    by_arm = []
    for arm, rows in sorted(groups.items()):
        valid = [row for row in rows if row.validation_status is ValidationStatus.VALID]

        def mean(name: str, source=rows):
            values = [getattr(row, name) for row in source if getattr(row, name) is not None]
            return sum(values) / len(values) if values else None

        values = {
            "attempted": len(rows),
            "transport_success": sum(row.transport_status in {
                TransportStatus.SUCCESS, TransportStatus.NOT_APPLICABLE,
            } for row in rows),
            "validation_success": len(valid),
            "semantic_correct": sum(row.semantic_correct for row in rows),
            "semantic_accuracy_all": mean("semantic_correct"),
            "source_coverage": mean("source_coverage"),
            "unknown_source_coverage": mean("unknown_source_coverage"),
            "feature_coverage": mean("feature_coverage"),
            "feature_accuracy_covered": mean("feature_accuracy_covered", valid),
            "feature_accuracy_all": mean("feature_accuracy_all"),
            "relation_precision": mean("relation_precision", valid),
            "relation_recall": mean("relation_recall", valid),
            "effect_precision": mean("effect_precision", valid),
            "effect_recall": mean("effect_recall", valid),
            "operator_precision": mean("operator_precision", valid),
            "operator_recall": mean("operator_recall", valid),
        }
        by_arm.append((arm, tuple(sorted(values.items()))))
    return PolicyBenchmarkReport(run.benchmark_sha256, tuple(scored), tuple(by_arm))

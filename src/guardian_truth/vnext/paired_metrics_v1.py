"""Post-seal paired X0/vNext outcome statistics, not a prediction or gold loader.

Inputs are explicit joined case records. Callers must validate prediction seals
BEFORE constructing these records; this module never opens a label file.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import comb
from random import Random

from .types import CoreStatus, CoverageStatus

STATUS = frozenset(item.value for item in CoreStatus)
COVERAGE = frozenset(item.value for item in CoverageStatus)


@dataclass(frozen=True)
class PairedOutcome:
    case_id: str
    trajectory_id: str
    category: str
    gold: int
    x0_binary: int
    vnext_binary: int
    core_status: str
    used_fallback: bool
    certificate_present: bool
    certificate_valid: bool | None
    coverage: str
    unresolved_reasons: tuple[str, ...] = ()

    def __post_init__(self):
        if not all(isinstance(item, str) and item for item in (self.case_id, self.trajectory_id, self.category)):
            raise ValueError("explicit case, trajectory group and category required")
        if any(type(item) is not int or item not in (0, 1) for item in (self.gold, self.x0_binary, self.vnext_binary)):
            raise ValueError("paired binary outputs and gold must be actual 0/1 ints")
        if self.core_status not in STATUS or self.coverage not in COVERAGE:
            raise ValueError("canonical Core status and semantic coverage required")
        if type(self.used_fallback) is not bool or type(self.certificate_present) is not bool:
            raise ValueError("fallback/certificate presence must be explicit")
        if self.certificate_valid is not None and type(self.certificate_valid) is not bool:
            raise ValueError("certificate validity is true/false or not evaluated")
        definite = self.core_status in {CoreStatus.PROVED_ERROR.value, CoreStatus.PROVED_NO_ERROR.value}
        if self.used_fallback == definite:
            raise ValueError("definite Core status cannot use product fallback; unresolved must disclose it")
        expected = 1 if self.core_status in {CoreStatus.PROVED_ERROR.value, CoreStatus.INCONSISTENT.value} else 0
        if self.vnext_binary != expected:
            raise ValueError("fixed competition mapping mismatch")
        if self.certificate_present and not definite:
            raise ValueError("unresolved/inconsistent status cannot claim a definitive certificate")
        if not self.certificate_present and self.certificate_valid is not None:
            raise ValueError("absent certificate cannot have a validity result")
        if type(self.unresolved_reasons) is not tuple or any(not isinstance(item, str) or not item for item in self.unresolved_reasons):
            raise ValueError("stable reason-code tuple required")


def _ratio(a, b):
    return a / b if b else None


def confusion(rows, field):
    tp = sum(row.gold == 1 and getattr(row, field) == 1 for row in rows)
    fp = sum(row.gold == 0 and getattr(row, field) == 1 for row in rows)
    fn = sum(row.gold == 1 and getattr(row, field) == 0 for row in rows)
    tn = sum(row.gold == 0 and getattr(row, field) == 0 for row in rows)
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    specificity = _ratio(tn, tn + fp)
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "precision": precision, "recall": recall, "F1": _ratio(2 * tp, 2 * tp + fp + fn),
        "false_positive_rate": _ratio(fp, fp + tn),
        "balanced_error": (2 - recall - specificity) / 2 if recall is not None and specificity is not None else None}


def exact_mcnemar(rows):
    """Two-sided exact paired correctness test; no asymptotic approximation."""
    x0_only = sum(row.x0_binary == row.gold and row.vnext_binary != row.gold for row in rows)
    vnext_only = sum(row.vnext_binary == row.gold and row.x0_binary != row.gold for row in rows)
    n = x0_only + vnext_only
    p = min(1.0, 2 * sum(comb(n, k) for k in range(min(x0_only, vnext_only) + 1)) / (2 ** n)) if n else 1.0
    return {"x0_only_correct": x0_only, "vnext_only_correct": vnext_only,
        "discordant": n, "two_sided_exact_p": p}


def _percentile(values, q):
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(position)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (position - low)


def hierarchical_bootstrap(rows, *, draws=5000, seed=260913):
    """Paired two-level resampling: trajectories, then cases within each draw.

    Undefined F1/recall draws remain undefined. A CI is reported only when all
    5000 draws have both required denominators, never after silently dropping
    unfavorable or degenerate samples.
    """
    if type(draws) is not int or draws < 1 or type(seed) is not int:
        raise ValueError("explicit positive draw count and integer seed required")
    groups = defaultdict(list)
    for row in rows:
        groups[row.trajectory_id].append(row)
    keys = sorted(groups)
    if not keys:
        raise ValueError("nonempty paired groups required")
    rng = Random(seed)
    differences = {"F1": [], "recall": [], "false_positive_rate": []}
    for _ in range(draws):
        sample = []
        for _ in keys:
            group = groups[rng.choice(keys)]
            sample.extend(rng.choice(group) for _ in group)
        baseline, candidate = confusion(sample, "x0_binary"), confusion(sample, "vnext_binary")
        for metric in differences:
            left, right = baseline[metric], candidate[metric]
            differences[metric].append(None if left is None or right is None else right - left)
    intervals = {}
    for metric, values in differences.items():
        defined = [value for value in values if value is not None]
        intervals[metric] = {"defined_draws": len(defined), "total_draws": draws,
            "CI95": [_percentile(defined, .025), _percentile(defined, .975)] if len(defined) == draws else None}
    return {"method": "PAIRED_HIERARCHICAL_TRAJECTORY_THEN_WITHIN_GROUP_CASE_BOOTSTRAP",
        "seed": seed, "draws": draws, "trajectory_groups": len(keys), "delta_intervals": intervals}


def summarize_paired_outcomes(rows, *, draws=5000, seed=260913):
    rows = tuple(rows)
    if not rows or any(not isinstance(row, PairedOutcome) for row in rows):
        raise ValueError("nonempty validated paired outcomes required")
    if len({row.case_id for row in rows}) != len(rows):
        raise ValueError("case IDs must be unique")
    x0, candidate = confusion(rows, "x0_binary"), confusion(rows, "vnext_binary")
    by_category = defaultdict(list)
    for row in rows:
        by_category[row.category].append(row)
    status = Counter(row.core_status for row in rows)
    definite = [row for row in rows if row.core_status in {CoreStatus.PROVED_ERROR.value, CoreStatus.PROVED_NO_ERROR.value}]
    certified = [row for row in definite if row.certificate_present and row.certificate_valid is True]
    certificate = {}
    for kind in (CoreStatus.PROVED_ERROR.value, CoreStatus.PROVED_NO_ERROR.value):
        matching = [row for row in definite if row.core_status == kind]
        present = sum(row.certificate_present for row in matching)
        valid = sum(row.certificate_valid is True for row in matching)
        certificate[kind] = {"definite": len(matching), "present": present, "valid": valid,
            "validation_rate_all_definite": _ratio(valid, len(matching)),
            "validation_rate_present": _ratio(valid, present)}
    return {"scope": "POST_SEAL_PAIRED_BINARY_AND_CORE_DIAGNOSTICS_NOT_PROOF_OF_MODEL_GAIN",
        "case_count": len(rows), "x0": x0, "vnext": candidate,
        "delta": {metric: candidate[metric] - x0[metric] if candidate[metric] is not None and x0[metric] is not None else None
            for metric in ("F1", "recall", "false_positive_rate")},
        "core_status_distribution": dict(status),
        "claimed_definitive_count": len(definite), "claimed_core_resolution_rate": len(definite) / len(rows),
        "certified_definitive_count": len(certified), "core_resolution_rate": len(certified) / len(rows),
        "uncertified_definitive_case_ids": [row.case_id for row in definite
            if not row.certificate_present or row.certificate_valid is not True],
        "fallback_count": sum(row.used_fallback for row in rows),
        "semantic_coverage_distribution": dict(Counter(row.coverage for row in rows)),
        "unresolved_reason_distribution": dict(Counter(reason for row in rows
            if row.core_status in {CoreStatus.UNRESOLVED.value, CoreStatus.INCONSISTENT.value}
            for reason in row.unresolved_reasons)),
        "certificate_validation_by_verdict": certificate,
        "confident_wrong_case_ids": [row.case_id for row in definite if row.vnext_binary != row.gold],
        "category_confusion": {category: {"x0": confusion(subset, "x0_binary"),
            "vnext": confusion(subset, "vnext_binary")} for category, subset in sorted(by_category.items())},
        "mcnemar": exact_mcnemar(rows), "paired_bootstrap": hierarchical_bootstrap(rows, draws=draws, seed=seed),
        "transport_reliability": "NOT_IN_THIS_POST_SEAL_INPUT", "schema_reliability": "NOT_IN_THIS_POST_SEAL_INPUT",
        "latency": "NOT_IN_THIS_POST_SEAL_INPUT", "tokens": "NOT_IN_THIS_POST_SEAL_INPUT", "cost": "NOT_AUDITED"}

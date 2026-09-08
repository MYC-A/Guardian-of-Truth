"""Offline falsification metrics for the underspecified-semantics prototype."""

from collections import Counter
from typing import Iterable, Mapping

from .semantic_feature_adapter import semantic_feature_view
from .semantic_metamorphic import run_metamorphic_suite
from .underspecified_semantics import (
    StandardFactors, analyze_rule, build_outer_space,
    counterfactual_factor_sensitivity, evaluate_structured_standard,
    information_insufficiency_witness, residual_invariant,
)


def _gold_atoms(case: Mapping) -> set[str]:
    gold = case["gold"]
    atoms = set()
    for relation in gold.get("relations", ()):
        if relation in {"IF", "ONLY_IF", "IFF"}:
            atoms.add(f"direction:{relation}")
    for operator in gold.get("operators", ()):
        if operator in {"AND", "OR"}:
            atoms.add(f"connective:{operator}")
        elif operator == "NOT":
            atoms.add("negation")
        elif operator in {"BEFORE", "AFTER", "IS_PAST", "DATE_LT"}:
            atoms.add(f"temporal:{operator}")
        elif operator in {"LT", "LE", "GT", "GE"}:
            atoms.add(f"comparison:{operator}")
        elif operator in {"COUNT", "COUNT_TRUE"}:
            atoms.add("cardinality")
    features = gold.get("features", {})
    for name in ("modality", "quantifier"):
        value = features.get(name)
        if value and value != "NONE":
            atoms.add(f"{name}:{value}")
    if features.get("negation"):
        atoms.add("negation")
    if features.get("exception"):
        atoms.add("exception")
    return atoms


def _actual_atoms(rule: str) -> tuple[set[str], object]:
    analysis = analyze_rule(rule)
    atoms = set()
    for item in analysis.obligations:
        value = item.alternatives[0] if item.alternatives else None
        if item.kind == "CONDITION_DIRECTION":
            atoms.add(f"direction:{value}")
        elif item.kind == "CONNECTIVE":
            atoms.add(f"connective:{value}")
        elif item.kind == "NEGATION":
            atoms.add("negation")
        elif item.kind == "EXCEPTION":
            atoms.add("exception")
        elif item.kind == "DISCOURSE_ATTACHMENT":
            atoms.add("exception")
        elif item.kind == "MODALITY":
            atoms.add(f"modality:{value}")
        elif item.kind == "QUANTIFIER":
            atoms.add(f"quantifier:{value}")
        elif item.kind == "COMPARISON":
            atoms.add(f"comparison:{value}")
        elif item.kind == "TEMPORAL_RELATION":
            normalized = {"BEFORE": "BEFORE", "AFTER": "AFTER", "GT": "GT", "GE": "GE"}.get(value)
            if normalized in {"GT", "GE"}:
                atoms.add(f"comparison:{normalized}")
            elif normalized:
                atoms.add(f"temporal:{normalized}")
    return atoms, analysis


def evaluate_real_rules(cases: Iterable[Mapping]) -> dict:
    reports = []
    gold_total = matched_total = 0
    for case in cases:
        gold = _gold_atoms(case)
        actual, analysis = _actual_atoms(case["rule"])
        matched = gold & actual
        missing = gold - actual
        invented = actual - gold
        space = build_outer_space(analysis)
        gold_total += len(gold)
        matched_total += len(matched)
        reports.append({
            "case_id": case["case_id"],
            "gold_feature_requirements": sorted(gold),
            "represented": sorted(matched),
            "missing": sorted(missing),
            "extra_detected": sorted(invented),
            "complete": not missing,
            "outer_width": space.width(),
            "gold_audit_gate_passed": not missing and not analysis.issues,
        })
    complete = sum(item["complete"] for item in reports)
    return {
        "cases": len(reports),
        "gold_unique_feature_requirements": gold_total,
        "represented_unique_feature_requirements": matched_total,
        "formalization_feature_coverage": matched_total / gold_total if gold_total else None,
        "case_complete_rate": complete / len(reports) if reports else None,
        "construction_missing_case_rate": 1 - complete / len(reports) if reports else None,
        "gold_audit_gate_passed_cases": sum(item["gold_audit_gate_passed"] for item in reports),
        "automatic_strict_verdicts_from_new_semantic_path": 0,
        "outer_width": {
            "max": max((item["outer_width"] for item in reports), default=0),
            "mean": (sum(item["outer_width"] for item in reports) / len(reports)
                     if reports else None),
        },
        "reports": reports,
        "scope": ("recall of unique per-rule feature tags after set projection; not occurrence-level "
                  "obligation coverage and not proof that an admissible interpretation is in outer"),
    }


def evaluate_row_slice(cases: Iterable[Mapping]) -> dict:
    """Compare A with a non-integrated D/E prototype on manual invariant labels.

    D/E retain already integrated exact routes. All semantic routes abstain because
    this prototype intentionally has no trace compiler yet.
    """
    reports = []
    expected_counts = Counter()
    for case in cases:
        expected = case["invariant_expected_verdict"]
        expected_counts[expected] += 1
        baseline_positive = case["baseline"]["prediction"] == 1
        exact = str(case["baseline"].get("route", "")).startswith("exact:")
        candidate = (("PROVED_VIOLATION" if baseline_positive else "PROVED_NO_VIOLATION")
                     if exact else "UNRESOLVED")
        if expected == "PROVED_VIOLATION":
            baseline_invariant = baseline_positive
        elif expected == "PROVED_NO_VIOLATION":
            baseline_invariant = not baseline_positive
        else:
            baseline_invariant = False
        reports.append({
            "row_id": case["row_id"],
            "A_prediction": int(baseline_positive),
            "A_status": case["baseline"]["status"],
            "manual_invariant": expected,
            "D_status": candidate,
            "E_status": candidate,
            "A_decision_invariant": baseline_invariant,
            "changed_internal_status": not exact,
        })
    n = len(reports)
    old_errors = [item for item in reports if item["A_status"] in {"FP", "FN"}]
    strict_expected = [item for item in reports if item["manual_invariant"] != "UNRESOLVED"]
    candidate_strict = [item for item in reports if item["D_status"] != "UNRESOLVED"]
    candidate_wrong = [item for item in candidate_strict
                       if item["D_status"] != item["manual_invariant"]]
    return {
        "cases": n,
        "manual_invariant_counts": dict(expected_counts),
        "A_binary_correct_on_error_heavy_slice": sum(
            item["A_status"].startswith("TP") or item["A_status"].startswith("TN")
            for item in reports),
        "A_decisions_invariant": sum(item["A_decision_invariant"] for item in reports),
        "A_decision_non_invariant_rate": (sum(not item["A_decision_invariant"] for item in reports) / n
                                           if n else None),
        "D_E_determinate": len(candidate_strict),
        "D_E_determinacy": len(candidate_strict) / n if n else None,
        "D_E_confident_wrong": len(candidate_wrong),
        "D_E_confident_wrong_rate_among_strict": (len(candidate_wrong) / len(candidate_strict)
                                                    if candidate_strict else None),
        "D_E_over_abstention_on_manual_strict": sum(
            item["D_status"] == "UNRESOLVED" for item in strict_expected),
        "D_E_useful_uncertainty_on_old_errors": sum(
            item["D_status"] == "UNRESOLVED" for item in old_errors),
        "changed_internal_status_count": sum(item["changed_internal_status"] for item in reports),
        "contest_predictions_changed": 0,
        "full_validation_run": False,
        "reason_full_validation_not_run": "small-slice signal fails determinacy/coverage gate",
        "reports": reports,
    }


def auxiliary_experiments() -> dict:
    witness = information_insufficiency_witness([
        {"departure_time": "17:00", "arrival_time": "19:00", "violation": False},
        {"departure_time": "17:00", "arrival_time": "16:00", "violation": True},
    ], ["departure_time"], "violation")
    clear = StandardFactors(True, True, True, True, False, False)
    unknown = StandardFactors(True, True, True, None, False, False)
    return {
        "metamorphic": run_metamorphic_suite(semantic_feature_view),
        "information_insufficiency": {
            "found": witness.found,
            "projection": witness.projection,
            "opposite_outcomes": bool(witness.left and witness.right and
                                      witness.left["violation"] != witness.right["violation"]),
        },
        "semantic_residual": {
            "hard_core_invariant": residual_invariant(lambda residual: True or residual).status,
            "residual_changes_outcome": residual_invariant(lambda residual: residual).status,
        },
        "structured_standard": {
            "complete_factors": evaluate_structured_standard(clear),
            "missing_feasible_alternative": evaluate_structured_standard(unknown),
            "explained_override_only": evaluate_structured_standard(
                StandardFactors(None, None, None, None, None, True)),
            "counterfactual_sensitive": counterfactual_factor_sensitivity(
                clear, "feasible_alternative"),
        },
    }

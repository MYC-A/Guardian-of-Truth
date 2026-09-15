"""Final Policy cycle - fresh final holdout corpus builder + candidate
definitions (user sections 37-46).

One new Policy benchmark (100 cases, fresh domains/texts, 8-gram-disjoint
from V4, V5, PHV1, PSB, GRS Stage A and the never-run GRS Stage B corpus).
Gold is representation-independent: behavioral worlds over the shared v3
program space (the compiled target of ALL three frontends) plus the gold
DSL as reference canonical meaning; h0_representable is a per-case
capacity diagnostic, not a scoring input.

Everything here is deterministic: no LLM, no network, no wall-clock.
"""
from __future__ import annotations

from .policy_grs_causal_benchmark import (
    PolicyGRSCase, _word_ngrams, build_grs_cases, development_text_ngrams)
from .policy_grs_prospective_benchmark import build_grs_stage_b_benchmark
from .policy_grs import grs_worlds
from .integrity import digest

from .policy_final_holdout_entries1 import ENTRIES_PART1
from .policy_final_holdout_entries2 import ENTRIES_PART2

ENTRIES = ENTRIES_PART1 + ENTRIES_PART2

COHORT_PLAN = {
    "simple_flat": 11, "empty_gold_control": 1, "modality": 6,
    "condition": 6, "exception": 6, "negation": 5, "multiclause": 7,
    "per_clause_modality": 7, "per_clause_actor": 6, "scope": 9,
    "one_of_all_of": 4, "exception_attachment": 5,
    "condition_attachment": 5, "temporal": 4, "provenance": 3,
    "multi_axis": 8, "nl_prose_stress": 7,
}

REQUIRED_DETECTIONS = {
    "simple_flat": [], "empty_gold_control": [], "modality": ["modality_flip"],
    "condition": ["condition_exception_swap"], "exception": ["condition_exception_swap"],
    "negation": ["condition_exception_swap"], "multiclause": [],
    "per_clause_modality": ["modality_swap"], "per_clause_actor": ["actor_move"],
    "scope": [], "one_of_all_of": [], "exception_attachment": ["condition_exception_swap"],
    "condition_attachment": ["condition_exception_swap"], "temporal": [],
    "provenance": [], "multi_axis": ["condition_exception_swap"],
    "nl_prose_stress": [],
}


def final_holdout_novelty_ngrams() -> set:
    """8-gram novelty surface: every prior Policy corpus text (V4, V5, PHV1,
    PSB, GRS Stage A) plus the never-run GRS Stage B corpus texts."""
    ngrams = development_text_ngrams()
    from .policy_grs_causal_benchmark import build_grs_stage_a_benchmark
    for case in build_grs_stage_a_benchmark():
        ngrams |= _word_ngrams(case.policy)
    for case in build_grs_stage_b_benchmark():
        ngrams |= _word_ngrams(case.policy)
    return ngrams


def build_final_holdout() -> list[PolicyGRSCase]:
    """Build the frozen final holdout corpus deterministically (100 cases)
    with every machine self-check of the shared builder."""
    return build_grs_cases(ENTRIES, final_holdout_novelty_ngrams(),
                           COHORT_PLAN, required_detections=REQUIRED_DETECTIONS)


def benchmark_final_holdout_document(cases: list[PolicyGRSCase]) -> dict:
    rows = [case.as_dict() for case in cases]
    return {
        "schema_version": "guardian-vnext-policy-final-holdout-v1",
        "prereg": "docs/vnext/POLICY_FINAL_PREREG_V1.json",
        "frozen_before_predictions": True,
        "annotation_basis": "CONSTRUCTION_FROM_TEMPLATES_NOT_MODEL_LABELS",
        "cohorts": dict(COHORT_PLAN),
        "cases_sha256": digest(rows),
        "cases": rows,
    }

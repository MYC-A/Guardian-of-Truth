#!/usr/bin/env python3
"""Update outputs/vnext/pre_benchmark_soundness_audit.json for B4h-sound-v2
(final pre-benchmark verification: SND-11 fix + final_verification block)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "outputs/vnext/pre_benchmark_soundness_audit.json"
data = json.loads(PATH.read_text(encoding="utf-8"))

# ---- version + resulting candidate ----
data["version"] = "pre_benchmark_soundness_audit_v2_final_verification"
data["resulting_candidate"] = "B4h-sound-v2"

# ---- SND-11 finding appended ----
existing_ids = {f["id"] for f in data["findings"]}
if "SND-11" not in existing_ids:
    data["findings"].append({
        "id": "SND-11",
        "class": "FORMAL_SOUNDNESS_BUG",
        "module": "src/guardian_truth/vnext/e2e/world_integration_v1.py",
        "function": "_row_binds_entity / _collect_state_rows / "
                    "_prove_deterministic_action_atom._trusted_state_row",
        "invariant": "PROVED means PROVED FROM EXPLICIT TRUSTED PREMISES: a flat "
                     "root-scope result field next to an entity ref key carries no "
                     "trusted premise that it is entity STATE rather than an "
                     "operation envelope field, so ownership cannot be proved and "
                     "the row must not decide a state claim (abstain -> UNKNOWN)",
        "counterexample": "T1 pure reader (writes=(), fresh-read, preconditions ok) "
                          "returns {'account_id': 'A-1', 'status': 'SUCCESS'} where "
                          "status is the operation envelope; claim 'status of A-1 "
                          "is active' was refuted by the envelope row -> certified "
                          "PROVED_ERROR (false definitive from wrong field mapping)",
        "current_behavior_pre_fix": "PROVED_ERROR certified from the flat envelope row",
        "correct_behavior": "UNKNOWN / UNRESOLVED unless the T1 contract declares "
                            "the output path in `reads` (explicit ownership mapping) "
                            "or the row lives in a nested record object with the "
                            "entity ref (structural ownership)",
        "counterexample_test": "tests/e2e_soundness/test_pre_benchmark_soundness.py::"
                               "test_B05_flat_envelope_row_never_refutes",
        "fixed": True,
        "fix": "root-scope abstention + explicit ownership mapping via the existing "
               "T1 `reads` field (previously dead weight); applied identically to "
               "the state channel and the SND-09 gate fallback; gated behind "
               "conservative_state so B0 keeps byte fidelity",
    })

# ---- regression block update ----
data["regression"]["b4h_sound_v2_combined_144"] = {
    "TP": 49, "FP": 0, "FN": 20, "TN": 5,
    "precision": 1.0, "recall": 0.7101, "f1": 0.834,
    "false_certified_error": 0, "false_certified_no_error": 0,
    "uncertified_definitive": 0,
    "status_counts": {"UNRESOLVED": 90, "PROVED_ERROR": 49, "PROVED_NO_ERROR": 5},
    "cache_misses": 0,
    "binary_metrics_change_vs_b4h_sound_v1":
        "TP 54->49, FN 15->20, TN 19->5 (24 verdict changes, every one the sound "
        "cost of SND-11: claim verdicts resting solely on undeclared flat rows "
        "abstain); precision stays 1.000; false certifications stay 0; metric loss "
        "accepted per directive section 15",
}

# ---- freeze block update ----
data["freeze"]["version"] = "B4h-sound-v2"
data["freeze"]["frozen_component_sha256_16"]["world_integration_v1"] = "4b131180aab4e77f"
data["freeze"]["audit_content_commit"] = (
    "5e4bc39e57072e164ab3bf41665e2374f04c6432 (B4h-sound-v1 audit state); the "
    "final-verification commit adding SND-11 (this commit series); "
    "FINAL_FROZEN_COMMIT = the freeze commit recording this manifest")
data["freeze"]["changelog_v2"] = (
    "B4h-sound-v2 = B4h-sound-v1 + SND-11 (root-scope flat-row abstention + "
    "explicit T1 reads ownership mapping). SND-01..SND-10 unchanged and "
    "re-verified. Only world_integration_v1.py changed "
    "(1c989f652bfcf972 -> 4b131180aab4e77f).")
data["freeze"]["reproducible_commands"] = [
    "PYTHONPATH=src python -m pytest tests/e2e/ tests/e2e_soundness/ -q",
    "PYTHONPATH=src:. python scripts/run_soundness_regression.py",
    "PYTHONPATH=src:. python scripts/final_verify_inconsistent_to_error.py",
]

# ---- final verification block (directive section 18) ----
data["final_verification"] = {
    "inconsistent_to_error_cases": [
        {
            "case_id": "dev-023",
            "old_status_b4h": "INCONSISTENT",
            "status_b4h_sound_v1": "PROVED_ERROR",
            "status_b4h_sound_v2_final": "UNRESOLVED",
            "world_count": 1,
            "obligations": ["s0:factual:0 (claim 'record R-4 exists', must_be_true)"],
            "b4h_sound_v1_primitive_proofs": [
                {"atom": "exists[entity R-4] expected true", "truth": "FALSE",
                 "refuting_witness": "obs:e4:ee3c75c1aa7ac2584b786b7e6e00f02b375f80f5a55973c507b77322c3b7138f"}
            ],
            "unresolved_markers": [],
            "both_evidence": [],
            "classification": "A. SOUND_INDEPENDENT_ERROR",
            "classification_basis": "single FALSE safety witness = the response claim "
                                    "refuted by the freshest trusted fresh read; NO BOTH "
                                    "conjunct exists (cross-time pair is historical, "
                                    "SND-01); ablation removing the t1 mutation preserves "
                                    "PROVED_ERROR with the same witness; certificate "
                                    "valid with MISSING_VIOLATION_WITNESS enforced",
            "final_note": "under B4h-sound-v2 the flat undeclared fresh-read row abstains "
                          "(SND-11) -> UNRESOLVED (claim TRUE via verified effect, goal "
                          "closure premise unproven -> conservative downgrade; no "
                          "definitive, no inconsistency)"
        },
        {
            "case_id": "hold-099",
            "old_status_b4h": "INCONSISTENT",
            "status_b4h_sound_v1": "PROVED_ERROR",
            "status_b4h_sound_v2_final": "UNRESOLVED",
            "world_count": 1,
            "obligations": ["s0:factual:0 (claim 'subscription SUB-5520 exists', must_be_true)"],
            "b4h_sound_v1_primitive_proofs": [
                {"atom": "exists[entity SUB-5520] expected true", "truth": "FALSE",
                 "refuting_witness": "obs:e4:ee3c75c1aa7ac2584b786b7e6e00f02b375f80f5a55973c507b77322c3b7138f"}
            ],
            "unresolved_markers": [],
            "both_evidence": [],
            "classification": "A. SOUND_INDEPENDENT_ERROR",
            "classification_basis": "identical shape to dev-023 (fetch_subscription fresh "
                                    "read exists=false vs restore_record verified effect "
                                    "exists=true); independent-witness ablation positive",
            "final_note": "UNRESOLVED under B4h-sound-v2 (SND-11 abstention)"
        },
        {
            "case_id": "hold-100",
            "old_status_b4h": "INCONSISTENT",
            "status_b4h_sound_v1": "PROVED_ERROR",
            "status_b4h_sound_v2_final": "UNRESOLVED",
            "world_count": 1,
            "obligations": ["s0:factual:0 (claim 'claim CLM-1174 exists', must_be_true)"],
            "b4h_sound_v1_primitive_proofs": [
                {"atom": "exists[entity CLM-1174] expected true", "truth": "FALSE",
                 "refuting_witness": "obs:e4:ee3c75c1aa7ac2584b786b7e6e00f02b375f80f5a55973c507b77322c3b7138f"}
            ],
            "unresolved_markers": [],
            "both_evidence": [],
            "classification": "A. SOUND_INDEPENDENT_ERROR",
            "classification_basis": "identical shape to dev-023 (fetch_claim fresh read "
                                    "exists=false vs restore_record verified effect "
                                    "exists=true); independent-witness ablation positive",
            "final_note": "UNRESOLVED under B4h-sound-v2 (SND-11 abstention)"
        }
    ],
    "all_have_independent_false_witness": True,
    "inconsistency_collapse_bug_found": False,
    "inconsistency_collapse_analysis": "world-level lattice absorption "
        "[BOTH,UNKNOWN]->error TRUE exists (FDE), but the frozen certificate rule "
        "MISSING_VIOLATION_WITNESS (present verbatim at e7eb79c) rejects any "
        "PROVED_ERROR without an individual FALSE safety conjunct in every world -> "
        "conservative UNRESOLVED downgrade; pinned by tests N01/N02 (no independent "
        "violation -> NOT PROVED_ERROR), N03 (independent violation -> PROVED_ERROR "
        "allowed), N04 (BOTH alone -> INCONSISTENT)",
    "rep01_class": "FORMAL_SOUNDNESS_BUG (reclassified from "
        "REPRESENTATION_LIMITATION by the final-verification directive section 10)",
    "rep01_false_definitive_reachable": True,
    "rep01_false_definitive_evidence": "test B05 pre-fix: flat envelope "
        "{'account_id': 'A-1', 'status': 'SUCCESS'} refuted 'status of A-1 is "
        "active' -> certified PROVED_ERROR; directive sections 8-9 adversarial "
        "shapes (nested get_resource envelope; payment/shipment/operation "
        "multi-entity) pinned as tests B06-B08",
    "rep01_resolution": "FIXED as SND-11 in B4h-sound-v2: root-scope rows are "
        "attributable only via an explicit T1 `reads` declaration (explicit "
        "ownership mapping) or nested record-object structure; otherwise UNKNOWN "
        "(abstention). No T1 v2 schema, no snapshot system, no value heuristics "
        "introduced; the frozen corpus convention (reads=[]) abstains",
    "production_hardcoding": 0,
    "soundness_test_count": 46,
    "soundness_tests_passing": 46,
    "soundness_xfail_count": 0,
    "e2e_suite": "96 passed (tests/e2e/ + tests/e2e_soundness/)",
    "baseline_suite": "1481 passed + 9 failed; failure list byte-identical with the "
        "frozen commit (the same 9 pre-existing archival failures, stash-diff "
        "verified); zero new failures",
    "b0_byte_fidelity": True,
    "b4h_sound_v2_combined_144": {
        "TP": 49, "FP": 0, "FN": 20, "TN": 5,
        "precision": 1.0, "recall": 0.7101, "f1": 0.834,
        "false_certified_error": 0, "false_certified_no_error": 0,
        "uncertified_definitive": 0
    },
    "known_remaining_formal_soundness_bugs": [],
    "known_coverage_representation_limitations": [
        "COV-01 reader with unrelated writes abstains",
        "COV-02 nested business fields need path-anchored claim predicates",
        "COV-03 flag-channel coverage requires REP-02 semantic_equivalences",
        "COV-04 boolean-token state gates keep lexical token bridging (EMP-02)",
        "SND-11 coverage cost: undeclared flat reader rows abstain (recovery: T1 "
        "reads declarations, now consumed, or nested record objects)",
        "REP-02 semantic equivalences absent",
        "REP-03 contract-declared canonicalization absent",
        "REP-04 mixed per-field freshness unrepresentable",
        "REP-05 eventual consistency outside proof scope while T1 trusted",
        "REP-06 structured read failure semantics absent",
        "REP-07 async lifecycle stages unrepresented",
        "REP-08 DESIRED_OUTCOME 'must act' existentials outside V1 program space"
    ],
    "empirical_hypotheses_frozen_line": [
        "EMP-01 canonical-encoding literal coercion",
        "EMP-02 lexical gate-token bridging on trusted attributable rows",
        "EMP-03 entity-ref key conventions (id/_id/name)",
        "EMP-04 machine suffixes as grounding context",
        "EMP-05 attribution claims are field-value assertions under the frozen B0 "
        "claim convention (name matching over result payloads)"
    ],
    "ready_for_shared_benchmark": True,
    "readiness_rationale": "no known path from insufficient/ambiguous evidence to a "
        "definitive verdict: flat-envelope ownership abstains (SND-11), cross-time "
        "pairs are historical (SND-01), staleness is symmetric (SND-02), failed "
        "reads observe nothing (SND-05), BOTH/INCONSISTENT never certifies ERROR "
        "(MISSING_VIOLATION_WITNESS), every definitive verdict is certificate-backed "
        "(uncertified_definitive=0), production hardcoding = 0",
}

PATH.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
print("audit JSON updated for B4h-sound-v2")
print("findings:", len(data["findings"]), "| final_verification block present:",
      "final_verification" in data)

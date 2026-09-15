"""Offline selftest for the PHV1 prospective holdout runner.

Everything here is DETERMINISTIC and SYNTHETIC: a fake in-process backend
answers with payload-derived canned values built from the frozen corpus gold
(explicitly STUB values that exercise plumbing only; never real model
outputs; these tests never report model results). Covered: corpus
invariants (composition, gold self-score, 8-gram novelty vs V4/V5), H0
identity continuity against the sealed C-ALR freeze, prereg mirroring, the
full freeze -> smoke -> run-h0 -> seal -> score -> audit pipeline, the
repair path, seal discipline, unsupported-semantics counters, Wilson CI math
and rerun idempotence.
"""
import json
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import evaluate_vnext_policy_phv1 as runner  # noqa: E402
from guardian_truth.vnext import policy_v3_benchmark as v3  # noqa: E402
from guardian_truth.vnext import policy_phv1_holdout as phv1  # noqa: E402
from guardian_truth.vnext.integrity import digest  # noqa: E402
from guardian_truth.vnext.semantic import SYSTEM, Proposal  # noqa: E402


# ------------------------------------------------------------------ fake model

def _perturb(structure: dict) -> dict:
    """SYNTHETIC stub transformation: flip IF->ONLY_IF, flip condition_mode
    when >= 2 conditions, flip temporal BEFORE/AFTER."""
    value = dict(structure)
    if value.get("relation") == "IF":
        value["relation"] = "ONLY_IF"
    if len(value.get("condition_literals", [])) >= 2:
        value["condition_mode"] = ("ANY" if value.get("condition_mode", "ALL") == "ALL"
                                   else "ALL")
    if value.get("temporal") == "BEFORE":
        value["temporal"] = "AFTER"
    elif value.get("temporal") == "AFTER":
        value["temporal"] = "BEFORE"
    return value


class FakeBackend:
    """Deterministic in-process delegate mimicking DiagnosticSemanticBackend."""

    gold_by_policy: dict = {}
    break_policy: str = None

    def __init__(self, client, interval_seconds=10, checkpoint=None):
        self.client, self.checkpoint = client, checkpoint

    def _record(self, task, payload, schema):
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user",
            "content": "TASK: " + task + "\nDATA_JSON: "
                + json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
                + "\nOUTPUT_JSON_SCHEMA: " + json.dumps(schema, ensure_ascii=False,
                        sort_keys=True, separators=(",", ":"), allow_nan=False)}]
        return {"backend_version": "fake-selftest", "task": task,
                "input_sha256": digest(payload), "prompt_sha256": digest(messages),
                "schema_sha256": digest(schema), "served_model": "fake-selftest",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                "latency_ms": 1, "transport_status": "SUCCESS",
                "schema_status": "VALID", "schema_issues": [], "error_category": None}

    def propose(self, task, payload, schema):
        record = self._record(task, payload, schema)
        if self.checkpoint:
            self.checkpoint(record)
        base = FakeBackend.gold_by_policy.get(payload.get("policy_text"))
        if base is None:
            value = {"modality": "PERMISSION", "relation": "IF",
                     "target_clauses": [[payload["atom_catalog"][0]]],
                     "condition_literals": [], "exception_literals": [],
                     "condition_mode": "ALL", "exception_mode": "ALL",
                     "temporal": "NONE", "actor": "assistant",
                     "regulated_kind": "ACTION", "facet": "primary",
                     "identity": "ANY", "provenance": "ANY", "quantification": "ALL"}
            return Proposal(json.dumps(value, sort_keys=True, separators=(",", ":")),
                            "SUCCESS", "VALID")
        is_repair = "previous_output" in payload
        if (not is_repair and payload["policy_text"] == FakeBackend.break_policy):
            # exercise the frozen machine-validation repair path
            return Proposal(None, "SUCCESS", "INVALID")
        value = _perturb(base)
        return Proposal(json.dumps(value, sort_keys=True, separators=(",", ":")),
                        "SUCCESS", "VALID")


# ------------------------------------------------------------- corpus invariants

def _ngrams(text, n=8):
    words = text.lower().split()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def test_corpus_composition_gold_and_novelty():
    cases = phv1.build_phv1_holdout()
    assert len(cases) == 80
    cohorts = {}
    families = {}
    for case in cases:
        cohorts[case.cohort] = cohorts.get(case.cohort, 0) + 1
        families[case.family] = families.get(case.family, 0) + 1
    assert cohorts == {"simple": 20, "structural": 20, "multi_clause": 20,
                       "nl_stress": 12, "ambiguity": 8}
    assert families == phv1.FAMILY_PLAN
    ambiguous = [case for case in cases if case.ambiguous]
    assert len(ambiguous) == 8
    assert all(case.cohort == "ambiguity" for case in ambiguous)
    for case in cases:
        for structure in case.admissible_structures:
            ok, _, _ = v3.score_candidate_structure(dict(structure), case.worlds,
                                                    case.admissible_programs)
            assert ok, f"gold self-score failed: {case.case_id}"
        if case.family == "multi_axis":
            assert len(case.axes) >= 2
    # novelty: no shared word 8-gram with V4/V5, no internal duplicates
    from guardian_truth.vnext.policy_v4_benchmark import build_v4_benchmark
    from guardian_truth.vnext.policy_v5_benchmark import build_v5_benchmark
    old = set()
    for builder in (build_v4_benchmark, build_v5_benchmark):
        for case in builder():
            old |= _ngrams(case.policy)
    seen = {}
    for case in cases:
        assert not (_ngrams(case.policy) & old), f"novelty violation: {case.case_id}"
        for gram in _ngrams(case.policy):
            assert seen.get(gram, case.case_id) == case.case_id, "internal duplicate"
            seen.setdefault(gram, case.case_id)


def test_h0_identity_continuity_vs_sealed_c_alr_freeze():
    path = REPO / runner.C_ALR_FREEZE_PATH
    if not path.is_file():
        pytest.skip("sealed C-ALR freeze not present")
    c_alr = json.loads(path.read_text(encoding="utf-8"))
    assert runner.H0_IDENTITY["parse_task_sha256"] == c_alr["prompt_freeze"]["parse_task_sha256"]
    assert runner.H0_IDENTITY["repair_task_sha256"] == c_alr["prompt_freeze"]["repair_task_sha256"]
    assert runner.H0_IDENTITY["structure_schema_sha256"] == c_alr["prompt_freeze"]["structure_schema_sha256"]
    assert runner.H0_IDENTITY["definition_sha256"] == c_alr["definition_sha256"]


def test_gates_mirror_prereg():
    prereg = json.loads((REPO / runner.PREREG_DOC).read_text(encoding="utf-8"))
    assert runner.PHV1_GATES == prereg["gates"]
    assert prereg["corpus"]["composition"] == phv1.COHORT_PLAN


def test_wilson_ci_known_values():
    lo, hi = runner.wilson_ci(0, 10)
    assert lo == 0.0 and round(hi, 4) == 0.2775
    lo, hi = runner.wilson_ci(10, 10)
    assert round(lo, 4) == 0.7225 and round(hi, 4) == 1.0
    lo, hi = runner.wilson_ci(72, 80)
    assert round(lo, 4) == 0.8149 and round(hi, 4) == 0.9485
    lo, hi = runner.wilson_ci(76, 80)
    assert round(lo, 4) == 0.8784 and round(hi, 4) == 0.9804


def test_unsupported_counters_deterministic():
    from types import SimpleNamespace

    def world(facts):
        return {"facts": sorted(facts), "expected": "NO_VIOLATION"}

    # invented permission: pred UNLESS where gold is IF-negated
    gold = v3.compile_v3_structure({"modality": "PROHIBITION", "relation": "IF",
                                    "target_clauses": [["action:whip_cream"]],
                                    "condition_literals": ["!state:log_initialled"]})
    pred = v3.compile_v3_structure({"modality": "PROHIBITION", "relation": "UNLESS",
                                    "target_clauses": [["action:whip_cream"]],
                                    "exception_literals": ["state:log_initialled"]})
    case = SimpleNamespace(admissible_programs=[gold], ambiguous=False,
                           worlds=[world({"action:whip_cream", "state:log_initialled"})])
    counters = runner._unsupported_counters(case, pred, correct=False)
    assert counters["invented_permission"] is True

    # wrong polarity: same atom, flipped negation
    gold2 = v3.compile_v3_structure({"modality": "PERMISSION", "relation": "ONLY_IF",
                                     "target_clauses": [["action:mow"]],
                                     "condition_literals": ["!event:count_begun"]})
    pred2 = v3.compile_v3_structure({"modality": "PERMISSION", "relation": "ONLY_IF",
                                     "target_clauses": [["action:mow"]],
                                     "condition_literals": ["event:count_begun"]})
    case2 = SimpleNamespace(admissible_programs=[gold2], ambiguous=False,
                            worlds=[world({"action:mow"})])
    assert runner._unsupported_counters(case2, pred2, correct=False)["wrong_polarity"] is True

    # invented exception + unsupported restrictive scope (split where gold merged)
    gold3 = v3.compile_v3_structure({"modality": "PROHIBITION", "relation": "UNCONDITIONAL",
                                     "target_clauses": [["action:run_buffer", "action:run_polisher"]]})
    pred3 = v3.compile_v3_structure({"modality": "PROHIBITION", "relation": "UNCONDITIONAL",
                                     "target_clauses": [["action:run_buffer"], ["action:run_polisher"]],
                                     "exception_literals": ["state:supervisor_present"]})
    case3 = SimpleNamespace(admissible_programs=[gold3], ambiguous=False,
                            worlds=[world({"action:run_buffer"})])
    counters3 = runner._unsupported_counters(case3, pred3, correct=False)
    assert counters3["invented_exception"] is True
    assert counters3["unsupported_restrictive_scope"] is True

    # invented requirement: silence turned into obligation
    gold4 = v3.compile_v3_structure({"modality": "PERMISSION", "relation": "IF",
                                     "target_clauses": [["action:do_job"]],
                                     "condition_literals": ["state:permit_held"]})
    pred4 = v3.compile_v3_structure({"modality": "REQUIREMENT", "relation": "UNCONDITIONAL",
                                     "target_clauses": [["state:job_done"]]})
    case4 = SimpleNamespace(admissible_programs=[gold4], ambiguous=False,
                            worlds=[world(set())])
    assert runner._unsupported_counters(case4, pred4, correct=False)["invented_requirement"] is True

    # invented condition: gold has no gates at all
    gold5 = v3.compile_v3_structure({"modality": "PROHIBITION", "relation": "UNCONDITIONAL",
                                     "target_clauses": [["action:smoke_terrace"]]})
    pred5 = v3.compile_v3_structure({"modality": "PROHIBITION", "relation": "UNCONDITIONAL",
                                     "target_clauses": [["action:smoke_terrace"]],
                                     "condition_literals": ["state:windy"]})
    case5 = SimpleNamespace(admissible_programs=[gold5], ambiguous=False,
                            worlds=[world({"action:smoke_terrace"})])
    assert runner._unsupported_counters(case5, pred5, correct=False)["invented_condition"] is True


# ------------------------------------------------------------- pipeline smoke

@pytest.fixture()
def smoke(tmp_path, monkeypatch):
    out = tmp_path / "phv1_out"
    out.mkdir()
    assert runner.phase_freeze(REPO, out) == 0
    bench = json.loads((out / f"{runner.PREFIX}_benchmark.json").read_text())
    FakeBackend.gold_by_policy = {row["policy"]: row["admissible_structures"][0]
                                  for row in bench["cases"]}
    FakeBackend.break_policy = bench["cases"][0]["policy"]
    monkeypatch.setattr(runner, "load_env_file", lambda path: None)
    monkeypatch.setattr(runner, "ChatClient", lambda config: None)
    monkeypatch.setattr(runner, "provider_config",
                        lambda config, backend, model=None: None)
    monkeypatch.setattr(runner, "DiagnosticSemanticBackend", FakeBackend)
    assert runner.phase_smoke(None, REPO, out) == 0
    assert runner.phase_run_h0(None, REPO, out, minutes=60) == 0
    assert runner.phase_score(REPO, out) == 0
    assert runner.phase_audit(REPO, out) == 0
    return out


def _expected_correct():
    cases = phv1.build_phv1_holdout()
    total = 0
    for case in cases:
        stub = _perturb(dict(case.admissible_structures[0]))
        ok, _, _ = v3.score_candidate_structure(stub, case.worlds, case.admissible_programs)
        total += ok
    return total


def test_smoke_pipeline_artifacts_seals_and_math(smoke):
    out = smoke
    for name in ("freeze", "benchmark", "smoke", "predictions", "prediction_seal",
                 "results", "failure_audit"):
        assert (out / f"{runner.PREFIX}_{name}.json").is_file(), name
    seal = json.loads((out / f"{runner.PREFIX}_prediction_seal.json").read_text())
    assert seal["gold_joined"] is False and seal["count"] == 80
    results = json.loads((out / f"{runner.PREFIX}_results.json").read_text())
    assert results["case_count"] == 80
    assert results["primary_metric"]["correct"] == _expected_correct()
    assert (results["primary_metric"]["overall_behavioral_accuracy"]
            == round(_expected_correct() / 80, 4))
    lo, hi = results["primary_metric"]["wilson_ci95"]
    assert 0.0 <= lo <= results["primary_metric"]["overall_behavioral_accuracy"] <= hi <= 1.0
    assert results["validity"]["schema_compile_validity"] == 1.0
    assert results["validity"]["ok_repaired"] >= 1  # break_policy exercised the repair path
    assert results["verdict"] in ("PROMOTE_TO_INTEGRATION", "REVISE",
                                  "REOPEN_POLICY_RESEARCH")
    assert results["historical_context"]["historical_arm_c"]["status"] == "USER_REPORTED_UNVERIFIED"
    assert results["historical_context"]["h0_v5_recovered"]["status"] == "MACHINE_VERIFIED"
    # stub flips IF->ONLY_IF: those must be counted as unsupported restrictive readings
    assert results["unsupported_semantics"]["unsupported_restrictive_scope"] >= 1
    assert results["structural_secondary"]["not_measured"]["provenance"] == "NOT_MEASURED"
    for family, metrics in results["families"].items():
        assert metrics["correct"] <= metrics["n"]
    assert sum(m["n"] for m in results["families"].values()) == 80


def test_smoke_audit_classification(smoke):
    audit = json.loads((smoke / f"{runner.PREFIX}_failure_audit.json").read_text())
    results = json.loads((smoke / f"{runner.PREFIX}_results.json").read_text())
    assert audit["error_count"] == 80 - results["primary_metric"]["correct"]
    allowed = {"modality", "relation", "condition_exception_binding", "negation_polarity",
               "condition_literals", "exception_literals", "condition_mode",
               "exception_mode", "target_atoms", "scope_shape", "temporal",
               "multi_axis", "representation_gap", "other"}
    for error in audit["errors"]:
        assert error["classification"] in allowed
    # the stub's dominant perturbation is a relation flip (IF -> ONLY_IF)
    assert audit["classes"].get("relation", 0) >= 1


def test_smoke_reruns_idempotent(smoke):
    out = smoke
    assert runner.phase_smoke(None, REPO, out) == 0  # SMOKE_ALREADY_DONE
    assert runner.phase_run_h0(None, REPO, out, minutes=60) == 0  # ALREADY_SEALED
    assert runner.phase_score(REPO, out) == 0
    assert runner.phase_audit(REPO, out) == 0


def test_run_h0_refuses_without_smoke(tmp_path, monkeypatch):
    out = tmp_path / "phv1_nosmoke"
    out.mkdir()
    assert runner.phase_freeze(REPO, out) == 0
    monkeypatch.setattr(runner, "load_env_file", lambda path: None)
    assert runner.phase_run_h0(None, REPO, out, minutes=1) == 2

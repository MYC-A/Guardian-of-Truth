"""Offline selftest for the C-ALR reimplementation study runner.

Everything here is DETERMINISTIC and SYNTHETIC: a fake in-process backend
answers with payload-derived canned values (never gold, never real model
outputs). These tests validate the PLUMBING (freeze -> h0 -> stage-a -> h2 ->
score, sealing, patch policy, statistics), never report model results.
"""
import json
import math
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import evaluate_vnext_c_alr_reimpl as runner  # noqa: E402
from guardian_truth.vnext import policy_v3_benchmark as v3  # noqa: E402
from guardian_truth.vnext.integrity import digest  # noqa: E402
from guardian_truth.vnext.semantic import SYSTEM, Proposal  # noqa: E402


# ------------------------------------------------------------------ fake model

class FakeBackend:
    """Deterministic in-process delegate mimicking DiagnosticSemanticBackend's
    contract (telemetry appended via checkpoint BEFORE returning).

    The canned parse values are SYNTHETIC: the fixture injects a map built from
    the frozen benchmark's admissible structures (gold-derived STUB values used
    only to exercise plumbing; this is a fake model, never real data, and these
    tests never report model results). The stub perturbs every IF gold to
    ONLY_IF, flips condition_mode when two or more conditions exist, and flips
    temporal BEFORE/AFTER whenever set, so the pipeline sees a mix of correct,
    wrong-recoverable and wrong cases, and the verifier is maximally gullible
    (always SUPPORTED with a verbatim prefix span) so patch application and
    scoring are exercised."""

    instances: list = []
    gold_by_policy: dict = {}

    def __init__(self, client, interval_seconds=10, checkpoint=None):
        self.client, self.checkpoint = client, checkpoint
        self.calls = 0
        FakeBackend.instances.append(self)

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
        self.calls += 1
        if task == runner.PARSE_TASK or task == runner.REPAIR_TASK:
            base = FakeBackend.gold_by_policy.get(payload["policy_text"])
            if base is not None:
                value = dict(base)
                if value.get("relation") == "IF":
                    value["relation"] = "ONLY_IF"
                if len(value.get("condition_literals", [])) >= 2:
                    value["condition_mode"] = ("ANY" if value.get("condition_mode", "ALL") == "ALL"
                                                else "ALL")
                if value.get("temporal") == "BEFORE":
                    value["temporal"] = "AFTER"
                elif value.get("temporal") == "AFTER":
                    value["temporal"] = "BEFORE"
            else:
                value = {"modality": "PERMISSION", "relation": "IF",
                         "target_clauses": [[payload["atom_catalog"][0]]],
                         "condition_literals": [], "exception_literals": [],
                         "condition_mode": "ALL", "exception_mode": "ALL",
                         "temporal": "NONE", "actor": "assistant",
                         "regulated_kind": "ACTION", "facet": "primary",
                         "identity": "ANY", "provenance": "ANY",
                         "quantification": "ALL"}
        else:
            span = " ".join(payload["policy_text"].split()[:6])
            value = {"verdict": "SUPPORTED", "source_span": span,
                     "justification": "synthetic selftest stub"}
        record = self._record(task, payload, schema)
        if self.checkpoint:
            self.checkpoint(record)
        return Proposal(json.dumps(value, sort_keys=True, separators=(",", ":")),
                        "SUCCESS", "VALID")


@pytest.fixture()
def smoke(tmp_path, monkeypatch):
    """Run the whole study pipeline (all 142 frozen cases) with the fake
    backend. Returns (out_dir, stage_a_report, fake_instances)."""
    out = tmp_path / "smoke_out"
    out.mkdir()
    # full 142-case set: instant with the in-process fake backend; the stub
    # perturbation yields 33 wrong / 33 recoverable -> share 23.2% -> PROCEED_H2
    assert runner.phase_freeze(REPO, out, limit=142) == 0
    FakeBackend.instances = []
    bench = json.loads((out / f"{runner.PREFIX}_benchmark.json").read_text())
    FakeBackend.gold_by_policy = {row["policy"]: row["admissible_structures"][0]
                                  for row in bench["cases"]}

    monkeypatch.setattr(runner, "load_env_file", lambda path: None)
    monkeypatch.setattr(runner, "ChatClient", lambda config: None)
    monkeypatch.setattr(runner, "provider_config",
                        lambda config, backend, model=None: None)
    monkeypatch.setattr(runner, "DiagnosticSemanticBackend", FakeBackend)
    assert runner.phase_run_h0(None, REPO, out, minutes=60) == 0
    assert runner.phase_stage_a(REPO, out) == 0
    stage_a = json.loads((out / f"{runner.PREFIX}_stage_a.json").read_text())
    if stage_a["verdict"] == "REJECT_EARLY":
        assert runner.phase_run_h2(None, REPO, out, minutes=60) == 2
        return out, stage_a, FakeBackend.instances
    assert runner.phase_run_h2(None, REPO, out, minutes=60) == 0
    assert runner.phase_score(REPO, out) == 0
    return out, stage_a, FakeBackend.instances


def test_smoke_pipeline_artifacts_and_seals(smoke):
    out, stage_a, fakes = smoke
    n = 142
    assert stage_a["verdict"] == "PROCEED_H2"  # stub perturbation is recoverable
    for name in ("freeze", "benchmark", "predictions", "prediction_seal",
                 "stage_a", "h1_predictions", "h1_prediction_seal",
                 "h2_predictions", "h2_prediction_seal", "results"):
        assert (out / f"{runner.PREFIX}_{name}.json").is_file()
    rows = json.loads((out / f"{runner.PREFIX}_predictions.json").read_text())
    assert len(rows) == n and all(row["prediction"] for row in rows)
    seal = json.loads((out / f"{runner.PREFIX}_prediction_seal.json").read_text())
    assert seal["gold_joined"] is False and seal["count"] == n
    assert stage_a["summary"]["n_cases"] == n
    results = json.loads((out / f"{runner.PREFIX}_results.json").read_text())
    assert results["case_count"] == n
    assert results["verdict"] in ("KEEP", "REVISE", "REJECT", "REJECT_EARLY")
    assert 0.0 <= results["accuracy"]["h0"] <= 1.0
    assert 0.0 <= results["accuracy"]["h2"] <= 1.0
    assert results["paired_h2_vs_h0"]["mcnemar_exact_p"] is not None
    h2_seal = json.loads(
        (out / f"{runner.PREFIX}_h2_prediction_seal.json").read_text())
    assert h2_seal["gold_joined"] is False


def test_smoke_reruns_are_idempotent(smoke):
    out, _, _ = smoke
    assert runner.phase_run_h0(None, REPO, out, minutes=60) == 0  # ALREADY_SEALED
    assert runner.phase_stage_a(REPO, out) == 0
    assert runner.phase_run_h2(None, REPO, out, minutes=60) == 0
    assert runner.phase_score(REPO, out) == 0


def test_smoke_mutations_persisted_verbatim_span(smoke):
    out, _, _ = smoke
    h2_rows = [p for p in out.glob(f"{runner.PREFIX}_h2_case_*.json")]
    assert len(h2_rows) == 142
    for path in h2_rows:
        row = json.loads(path.read_text())
        for mutation in row["verifier_mutations"]:
            # fake spans are verbatim prefixes by construction -> survive gate
            assert mutation["span_verbatim"] is True
            assert mutation["verdict_machine"] == "SUPPORTED"
            for record in mutation["request_records"]:
                assert record["backend_version"] == "fake-selftest"
    # h2 predictions differ from h0 on at least one case (a patch was applied)
    h0_rows = json.loads((out / f"{runner.PREFIX}_predictions.json").read_text())
    h2_rows = json.loads((out / f"{runner.PREFIX}_h2_predictions.json").read_text())
    assert any(a["prediction"] != b["prediction"] for a, b in zip(h0_rows, h2_rows))


# ------------------------------------------------------------------- unit math

def test_catalog_diff_relation_flip_mappable():
    a = v3.compile_v3_structure({"modality": "PERMISSION", "relation": "IF",
        "target_clauses": [["action:a"]], "condition_literals": ["state:c"]})
    gold = v3.compile_v3_structure({"modality": "PERMISSION", "relation": "ONLY_IF",
        "target_clauses": [["action:a"]], "condition_literals": ["state:c"]})
    assert runner.catalog_diff(a, gold) == ["IF_TO_ONLY_IF"]
    assert runner.catalog_diff(gold, a) == ["ONLY_IF_TO_IF"]


def test_catalog_diff_unmappable_axes():
    base = {"modality": "PERMISSION", "relation": "IF",
            "target_clauses": [["action:a"]], "condition_literals": []}
    a = v3.compile_v3_structure(base)
    assert runner.catalog_diff(a, v3.compile_v3_structure(
        dict(base, modality="PROHIBITION"))) is None  # modality outside catalog
    assert runner.catalog_diff(a, v3.compile_v3_structure(
        dict(base, target_clauses=[["action:b"]]))) is None  # atom change
    assert runner.catalog_diff(a, v3.compile_v3_structure(
        dict(base, condition_literals=["state:other"]))) is None  # new literal
    assert runner.catalog_diff(a, v3.compile_v3_structure(
        dict(base, relation="UNLESS"))) is None  # relation pair not in catalog
    # actor swap only in the engine's patch direction: the catalog replaces
    # actor:X with actor:assistant, so only phi=actor:X -> gold=actor:assistant
    # is mappable; the engine cannot remove an actor literal or create one.
    assert runner.catalog_diff(
        v3.compile_v3_structure(dict(base, condition_literals=["actor:duty_engineer"])),
        v3.compile_v3_structure(dict(base, condition_literals=["actor:assistant"]))) \
        == ["ACTOR_BEARER_SWAP"]
    assert runner.catalog_diff(
        v3.compile_v3_structure(dict(base, condition_literals=["actor:duty_engineer"])),
        a) is None  # patch would leave actor:assistant, not remove the literal
    assert runner.catalog_diff(
        a, v3.compile_v3_structure(dict(base, condition_literals=["actor:duty_engineer"]))) \
        is None  # engine never proposes assistant -> X


def test_catalog_diff_clause_shapes_and_counts():
    base = {"modality": "PROHIBITION", "relation": "UNCONDITIONAL",
            "condition_literals": []}
    together = v3.compile_v3_structure(
        dict(base, target_clauses=[["action:x", "action:y"]]))
    separate = v3.compile_v3_structure(
        dict(base, target_clauses=[["action:x"], ["action:y"]]))
    assert runner.catalog_diff(together, separate) == ["CLAUSE_MERGE_TO_SPLIT"]
    assert runner.catalog_diff(separate, together) == ["CLAUSE_SPLIT_TO_MERGE"]
    # three mutations -> caller-side >2 rejection
    a = v3.compile_v3_structure({"modality": "PERMISSION", "relation": "IF",
        "target_clauses": [["action:x", "action:y"]],
        "condition_literals": ["state:p", "state:q"], "condition_mode": "ALL",
        "temporal": "AFTER"})
    gold = v3.compile_v3_structure({"modality": "PERMISSION", "relation": "ONLY_IF",
        "target_clauses": [["action:x"], ["action:y"]],
        "condition_literals": ["state:p", "state:q"], "condition_mode": "ANY",
        "temporal": "BEFORE"})
    diff = runner.catalog_diff(a, gold)
    # deterministic catalog_diff order: relation, condition_mode, exception_mode,
    # temporal, clause shape, actor
    assert diff == ["IF_TO_ONLY_IF", "COND_ALL_TO_ANY",
                    "TEMPORAL_AFTER_TO_BEFORE", "CLAUSE_MERGE_TO_SPLIT"]
    assert len(diff) == 4  # > 2 -> caller rejects as REQUIRES_GLOBAL_REPARSE
    # temporal NONE <-> BEFORE/AFTER is outside the catalog -> unmappable
    assert runner.catalog_diff(a, v3.compile_v3_structure(
        dict(gold, temporal="NONE"))) is None


def test_risk_gate_deterministic():
    assert runner.risk_gated("You may renew the licence only while open.", "IF_TO_ONLY_IF")
    assert not runner.risk_gated("The key never leaves the room.", "COND_ANY_TO_ALL") \
        or "and" in "the key never leaves the room."  # no coordination words -> gated off


def test_assemble_phi_h_conflict_and_cap():
    program = v3.compile_v3_structure({"modality": "PERMISSION", "relation": "IF",
        "target_clauses": [["action:x", "action:y"]],
        "condition_literals": ["state:p", "state:q"], "condition_mode": "ALL"})
    proposals = v3.propose_mutations(program)
    # admit everything: relation + clause + mode mutations all SUPPORTED
    admitted = proposals
    patched, applied = runner.assemble_phi_h(program, admitted)
    fields = [patch["field"] for patch in applied]
    assert len(applied) == 2 and len(set(fields)) == 2  # cap of 2, one per field
    assert applied[0]["field"] == "relation"  # catalog order first
    assert patched["relation"] != program["relation"]
    # a single-field double admission applies only once
    rel_only = [p for p in proposals if p["mutation_type"] in
                ("IF_TO_ONLY_IF", "IF_TO_IF_AND_ONLY_IF")]
    patched2, applied2 = runner.assemble_phi_h(program, rel_only)
    assert len(applied2) == 1


def test_mcnemar_exact_p_known_values():
    assert runner.mcnemar_exact_p(0, 0) == 1.0
    assert runner.mcnemar_exact_p(5, 5) == 1.0
    assert abs(runner.mcnemar_exact_p(0, 10) - 2 * (0.5 ** 10)) < 1e-12
    n, b, c = 10, 8, 2
    expected = min(1.0, 2 * sum(math.comb(n, i) for i in range(0, 3)) * 0.5 ** n)
    assert abs(runner.mcnemar_exact_p(b, c) - expected) < 1e-12


def test_newcombe_ci_directional():
    # clear positive effect -> CI above zero; clear negative -> below zero
    lower_pos, upper_pos = runner.newcombe_paired_ci(20, 2, 100)
    assert lower_pos > 0
    lower_neg, upper_neg = runner.newcombe_paired_ci(2, 20, 100)
    assert upper_neg < 0
    lower_zero, upper_zero = runner.newcombe_paired_ci(7, 7, 100)
    assert lower_zero <= 0 <= upper_zero
    # includes the point estimate
    b, c, n = 12, 4, 60
    lower, upper = runner.newcombe_paired_ci(b, c, n)
    assert lower < (b - c) / n < upper

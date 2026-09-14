"""Offline selftest for the PSB causal experiment runner.

Everything here is DETERMINISTIC and SYNTHETIC: a fake in-process backend
answers with payload-derived canned values built from the frozen corpus gold
(explicitly STUB values that exercise plumbing only; never real model
outputs; these tests never report model results). Covered: corpus
invariants (composition, gold self-score, 8-gram novelty vs V4/V5/PHV1,
binding discriminability, h0-representability), compiler rule enforcement,
permission-gate marker classes and negation guards, canonical triple
projection consistency, composed scoring, binding metric math, McNemar /
Newcombe / Wilson math, prereg mirroring, H0 identity continuity vs the
sealed PHV1 freeze, the full freeze -> smoke -> run-h0 -> run-psb -> score
-> audit pipeline, the repair path, seal discipline and rerun idempotence.
"""
import json
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import evaluate_vnext_policy_psb as runner  # noqa: E402
from guardian_truth.vnext import policy_psb as psb  # noqa: E402
from guardian_truth.vnext import policy_psb_causal_benchmark as corpus  # noqa: E402
from guardian_truth.vnext import policy_v3_benchmark as v3  # noqa: E402
from guardian_truth.vnext.integrity import digest  # noqa: E402
from guardian_truth.vnext.semantic import SYSTEM, Proposal  # noqa: E402


# ------------------------------------------------------------------ fake model

def _perturb_flat(structure: dict) -> dict:
    """SYNTHETIC stub transformation of a flat H0 structure: IF->ONLY_IF,
    condition_mode flip when >= 2 conditions."""
    value = dict(structure)
    if value.get("relation") == "IF":
        value["relation"] = "ONLY_IF"
    if len(value.get("condition_literals", [])) >= 2:
        value["condition_mode"] = ("ANY" if value.get("condition_mode", "ALL") == "ALL"
                                   else "ALL")
    return value


class FakeBackend:
    """Deterministic in-process delegate mimicking DiagnosticSemanticBackend.
    Answers H0-schema requests with perturbed flat gold stubs and PSB-schema
    requests with the exact gold graph (SYNTHETIC stubs, plumbing only)."""

    flat_by_policy: dict = {}
    graph_by_policy: dict = {}
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
        is_repair = "previous_output" in payload
        if not is_repair and payload.get("policy_text") == FakeBackend.break_policy:
            return Proposal(None, "SUCCESS", "INVALID")
        if task == psb.PSB_PARSE_TASK:
            base = FakeBackend.graph_by_policy.get(payload.get("policy_text"))
            if base is None:  # synthetic smoke payload (non-benchmark)
                value = {"nodes": [corpus._regulated("n1", ["action:enter_crane_cab"]),
                                   corpus._modality("n2", "PERMISSION"),
                                   corpus._condition("n3", ["event:banksman_signalled"],
                                                     strength="NECESSARY")],
                         "edges": [corpus.E("REGULATES", "n2", "n1"),
                                   corpus.E("ACTIVATES", "n3", "n1")]}
            else:
                value = dict(base)
        else:
            base = FakeBackend.flat_by_policy.get(payload.get("policy_text"))
            if base is None:  # synthetic smoke payload (non-benchmark)
                value = {"modality": "PERMISSION", "relation": "ONLY_IF",
                         "target_clauses": [["action:open_paint_store"]],
                         "condition_literals": [], "exception_literals": [],
                         "condition_mode": "ALL", "exception_mode": "ALL",
                         "temporal": "NONE", "actor": "assistant",
                         "regulated_kind": "ACTION", "facet": "primary",
                         "identity": "ANY", "provenance": "ANY",
                         "quantification": "ALL"}
            else:
                value = _perturb_flat(dict(base))
        return Proposal(json.dumps(value, sort_keys=True, separators=(",", ":")),
                        "SUCCESS", "VALID")


# ------------------------------------------------------------- corpus invariants

def test_corpus_composition_gold_novelty_representability():
    cases = corpus.build_psb_causal_benchmark()
    assert len(cases) == 44
    cohorts = {}
    for case in cases:
        cohorts[case.cohort] = cohorts.get(case.cohort, 0) + 1
    assert cohorts == corpus.COHORT_PLAN == {
        "relation_attachment": 12, "exception_vs_condition": 8,
        "multiclause_modality_actor": 8, "permission_evidence_controls": 8,
        "multiaxis_controls": 8}
    # gold self-scores correct; every gold permission clause has a frozen marker
    for case in cases:
        programs = list(case.admissible_program_sets[0])
        correct, _ = psb.score_program_set(programs, case.worlds,
                                           case.admissible_program_sets)
        assert correct, f"gold self-score failed: {case.case_id}"
        for program in programs:
            if program["modality"] == "PERMISSION":
                assert psb.positive_permission_evidence(case.policy)["found"], \
                    f"gold permission without marker: {case.case_id}"
    # representability split (12 capacity cases: 8 M + r07 + x07 + p02 + p08)
    representable = sum(case.h0_representable for case in cases)
    assert representable == 32
    non_rep = {case.case_id for case in cases if not case.h0_representable}
    assert non_rep == {"relation::r07", "multi_axis::x07",
                       "permission_evidence::p02", "permission_evidence::p08"} \
        | {f"multiclause::m0{i}" for i in range(1, 9)}
    # novelty: no shared word 8-gram with V4/V5/PHV1, no internal duplicates
    from guardian_truth.vnext.policy_v4_benchmark import build_v4_benchmark
    from guardian_truth.vnext.policy_v5_benchmark import build_v5_benchmark
    from guardian_truth.vnext.policy_phv1_holdout import build_phv1_holdout

    def ngrams(text):
        words = ["".join(ch for ch in w.lower() if ch.isalnum())
                 for w in text.split()]
        words = [w for w in words if w]
        return {tuple(words[i:i + 8]) for i in range(len(words) - 7)}

    old = set()
    for builder, seed in ((build_v4_benchmark, 260914), (build_v5_benchmark, 260915),
                          (build_phv1_holdout, None)):
        for case in (builder() if seed is None else builder(seed=seed)):
            old |= ngrams(case.policy)
    seen = set()
    for case in cases:
        assert not (ngrams(case.policy) & old), f"novelty: {case.case_id}"
        assert not (ngrams(case.policy) & seen), f"internal dup: {case.case_id}"
        seen |= ngrams(case.policy)
    # binding discriminability: every non-empty-gold case separates at least
    # one perturbation; the empty-gold control has non-empty witness worlds
    for case in cases:
        if not case.admissible_program_sets[0]:
            assert any(case.worlds) and any(w["facts"] for w in case.worlds), \
                f"empty-gold case needs witness worlds: {case.case_id}"
            assert all(w["expected"] == "NO_VIOLATION" for w in case.worlds)
            continue
        report = corpus.binding_detection_report(case.admissible_program_sets,
                                                  case.worlds)
        assert any(entry["detected"] for entry in report.values()), \
            f"no detectable misbinding: {case.case_id}"


def test_gates_mirror_prereg():
    prereg = json.loads((REPO / runner.PREREG_DOC).read_text(encoding="utf-8"))
    assert runner.PSB_GATES == prereg["causal_gates"]
    assert prereg["causal_benchmark"]["composition"] == corpus.COHORT_PLAN
    assert prereg["causal_benchmark"]["size"] == 44
    final = prereg["final_holdout_conditional"]
    assert final["size"] == 88
    assert sum(final["composition"].values()) == 88


def test_h0_identity_continuity_vs_sealed_phv1_freeze():
    path = REPO / runner.PHV1_FREEZE_PATH
    if not path.is_file():
        pytest.skip("sealed PHV1 freeze not present")
    phv1 = json.loads(path.read_text(encoding="utf-8"))
    assert runner.H0_IDENTITY["parse_task_sha256"] == phv1["h0_identity"]["parse_task_sha256"]
    assert runner.H0_IDENTITY["repair_task_sha256"] == phv1["h0_identity"]["repair_task_sha256"]
    assert runner.H0_IDENTITY["structure_schema_sha256"] == phv1["h0_identity"]["structure_schema_sha256"]
    assert runner.H0_IDENTITY["definition_sha256"] == phv1["h0_identity"]["definition_sha256"]


# ------------------------------------------------------------ compiler rules

def _clause(modality="PERMISSION", relation=None, targets=(("action:x",),),
            conds=(), excs=(), mode="ALL", strength="SUFFICIENT"):
    nodes = [corpus._regulated("n1", [a for a in targets[0]]),
             corpus._modality("n2", modality)]
    edges = [corpus.E("REGULATES", "n2", "n1")]
    if conds:
        nodes.append(corpus._condition("n3", list(conds), mode=mode, strength=strength))
        edges.append(corpus.E("ACTIVATES", "n3", "n1"))
    if excs:
        nodes.append(corpus._exception("n4", list(excs)))
        edges.append(corpus.E("EXEMPTS", "n4", "n1"))
    return {"nodes": nodes, "edges": edges}


def test_compiler_relation_derivation_and_gates():
    # strength SUFFICIENT -> IF
    programs, _ = psb.compile_psb_graph(_clause(conds=["state:a"]))
    assert programs[0]["relation"] == "IF"
    # strength NECESSARY -> ONLY_IF
    programs, _ = psb.compile_psb_graph(_clause(conds=["state:a"], strength="NECESSARY"))
    assert programs[0]["relation"] == "ONLY_IF"
    # EXACTLY -> IF_AND_ONLY_IF
    programs, _ = psb.compile_psb_graph(_clause(conds=["state:a"], strength="EXACTLY"))
    assert programs[0]["relation"] == "IF_AND_ONLY_IF"
    # no gates -> UNCONDITIONAL
    programs, _ = psb.compile_psb_graph(_clause())
    assert programs[0]["relation"] == "UNCONDITIONAL"
    # actor non-exclusive -> IF; exclusive -> ONLY_IF
    graph = {"nodes": [corpus._regulated("n1", ["action:x"]),
                       corpus._modality("n2", "PERMISSION"),
                       corpus._actor("n3", "actor:nurse")],
             "edges": [corpus.E("REGULATES", "n2", "n1"),
                       corpus.E("ACTOR_OF", "n3", "n1")]}
    programs, _ = psb.compile_psb_graph(graph)
    assert programs[0]["relation"] == "IF"
    assert programs[0]["condition_literals"] == ["actor:nurse"]
    graph["nodes"][2] = corpus._actor("n3", "actor:nurse", exclusive=True)
    programs, _ = psb.compile_psb_graph(graph)
    assert programs[0]["relation"] == "ONLY_IF"
    # PRECEDES negates event literals and sets temporal BEFORE
    graph = {"nodes": [corpus._regulated("n1", ["action:x"]),
                       corpus._modality("n2", "PERMISSION"),
                       corpus._condition("n3", ["event:lockup"])],
             "edges": [corpus.E("REGULATES", "n2", "n1"),
                       corpus.E("PRECEDES", "n3", "n1")]}
    programs, _ = psb.compile_psb_graph(graph)
    assert programs[0]["condition_literals"] == ["!event:lockup"]
    assert programs[0]["temporal"] == "BEFORE"
    # FOLLOWS keeps events positive, temporal AFTER
    graph["edges"][1] = corpus.E("FOLLOWS", "n3", "n1")
    programs, _ = psb.compile_psb_graph(graph)
    assert programs[0]["condition_literals"] == ["event:lockup"]
    assert programs[0]["temporal"] == "AFTER"
    # REQUIREMENT + exception -> UNLESS; with a condition it is invalid
    programs, _ = psb.compile_psb_graph(_clause(modality="REQUIREMENT", excs=["state:b"]))
    assert programs[0]["relation"] == "UNLESS"
    with pytest.raises(psb.PSBInvalid):
        psb.compile_psb_graph(_clause(modality="REQUIREMENT", conds=["state:a"],
                                      excs=["state:b"]))
    # shared gates: one condition binding two clauses
    graph = {"nodes": [corpus._regulated("n1", ["action:x"]),
                       corpus._regulated("n2", ["action:y"]),
                       corpus._modality("n3", "PROHIBITION"),
                       corpus._condition("n4", ["state:a"])],
             "edges": [corpus.E("REGULATES", "n3", "n1"), corpus.E("REGULATES", "n3", "n2"),
                       corpus.E("ACTIVATES", "n4", "n1"), corpus.E("ACTIVATES", "n4", "n2")]}
    programs, _ = psb.compile_psb_graph(graph)
    assert len(programs) == 2
    assert all(p["relation"] == "IF" and p["condition_literals"] == ["state:a"]
               for p in programs)


def test_compiler_rule_enforcement():
    # duplicate node id
    with pytest.raises(psb.PSBInvalid):
        psb.compile_psb_graph({"nodes": [corpus._regulated("n1", ["action:x"]),
                                         corpus._regulated("n1", ["action:y"])],
                               "edges": []})
    # two REGULATES on one clause
    with pytest.raises(psb.PSBInvalid):
        psb.compile_psb_graph({"nodes": [corpus._regulated("n1", ["action:x"]),
                                         corpus._modality("n2", "PERMISSION"),
                                         corpus._modality("n3", "PROHIBITION")],
                               "edges": [corpus.E("REGULATES", "n2", "n1"),
                                         corpus.E("REGULATES", "n3", "n1")]})
    # no REGULATES
    with pytest.raises(psb.PSBInvalid):
        psb.compile_psb_graph({"nodes": [corpus._regulated("n1", ["action:x"]),
                                         corpus._modality("n2", "PERMISSION")],
                               "edges": []})
    # two ACTIVATES on one clause
    with pytest.raises(psb.PSBInvalid):
        psb.compile_psb_graph({"nodes": [corpus._regulated("n1", ["action:x"]),
                                         corpus._modality("n2", "PERMISSION"),
                                         corpus._condition("n3", ["state:a"]),
                                         corpus._condition("n4", ["state:b"])],
                               "edges": [corpus.E("REGULATES", "n2", "n1"),
                                         corpus.E("ACTIVATES", "n3", "n1"),
                                         corpus.E("ACTIVATES", "n4", "n1")]})
    # PRECEDES and FOLLOWS together
    with pytest.raises(psb.PSBInvalid):
        psb.compile_psb_graph({"nodes": [corpus._regulated("n1", ["action:x"]),
                                         corpus._modality("n2", "PERMISSION"),
                                         corpus._condition("n3", ["event:a"]),
                                         corpus._condition("n4", ["event:b"])],
                               "edges": [corpus.E("REGULATES", "n2", "n1"),
                                         corpus.E("PRECEDES", "n3", "n1"),
                                         corpus.E("FOLLOWS", "n4", "n1")]})
    # PRECEDES with a non-event literal
    with pytest.raises(psb.PSBInvalid):
        psb.compile_psb_graph({"nodes": [corpus._regulated("n1", ["action:x"]),
                                         corpus._modality("n2", "PERMISSION"),
                                         corpus._condition("n3", ["state:a"])],
                               "edges": [corpus.E("REGULATES", "n2", "n1"),
                                         corpus.E("PRECEDES", "n3", "n1")]})
    # disagreeing modes between plain and temporal conditions
    with pytest.raises(psb.PSBInvalid):
        psb.compile_psb_graph({"nodes": [corpus._regulated("n1", ["action:x"]),
                                         corpus._modality("n2", "PERMISSION"),
                                         corpus._condition("n3", ["state:a"], mode="ALL"),
                                         corpus._condition("n4", ["event:b"], mode="ANY")],
                               "edges": [corpus.E("REGULATES", "n2", "n1"),
                                         corpus.E("ACTIVATES", "n3", "n1"),
                                         corpus.E("FOLLOWS", "n4", "n1")]})
    # QUALIFIES cannot bind PROVENANCE
    with pytest.raises(psb.PSBInvalid):
        psb.compile_psb_graph({"nodes": [corpus._regulated("n1", ["claim:x"]),
                                         corpus._modality("n2", "REQUIREMENT"),
                                         corpus.N("n3", "QUALIFIER", kind="PROVENANCE",
                                                  value="evidence:log")],
                               "edges": [corpus.E("REGULATES", "n2", "n1"),
                                         corpus.E("QUALIFIES", "n3", "n1")]})
    # edge to a non-REGULATED target
    with pytest.raises(psb.PSBInvalid):
        psb.compile_psb_graph({"nodes": [corpus._regulated("n1", ["action:x"]),
                                         corpus._modality("n2", "PERMISSION")],
                               "edges": [corpus.E("REGULATES", "n1", "n2")]})
    # empty graph compiles to the empty program set
    programs, rejected = psb.compile_psb_graph({"nodes": [], "edges": []})
    assert programs == [] and rejected == []


def test_permission_gate_semantics():
    # unevidenced PERMISSION is rejected (dropped, recorded, never remapped)
    graph = _clause(modality="PERMISSION", conds=["state:a"])
    programs, rejected = psb.compile_psb_graph(
        graph, permission_gate=True, policy_text="The thing is available in bulk.")
    assert programs == []
    assert rejected == [{"target_clauses": [["action:x"]],
                         "reason": "no_positive_permission_evidence"}]
    # evidenced PERMISSION survives
    programs, rejected = psb.compile_psb_graph(
        graph, permission_gate=True, policy_text="Members may do the thing.")
    assert len(programs) == 1 and programs[0]["modality"] == "PERMISSION"
    assert rejected == []
    # non-permission clauses are never touched by the gate
    graph = _clause(modality="PROHIBITION", conds=["state:a"])
    programs, rejected = psb.compile_psb_graph(
        graph, permission_gate=True, policy_text="The thing is available in bulk.")
    assert len(programs) == 1 and rejected == []


def test_permission_evidence_marker_classes():
    cases = [
        ("Members may moor dinghies.", True),
        ("Under no circumstances may the key be lent.", False),
        ("No cream may be whipped.", False),
        ("Neither the rowers nor the coxes may launch.", False),
        ("Provided that the sheet does not show red, the hatch may stay open.", True),
        ("Only when the gauge is not showing amber may the well be inspected.", True),
        ("Holders are entitled to use the courts.", True),
        ("The door is not allowed to stay open.", False),
        ("It is open to any member to take the boat.", True),
        ("Dwell adjustment is reserved to the master weaver.", True),
        ("The lift can carry four adults.", False),
        ("Only with consent can the launch leave.", True),
        ("Nothing in the orders bars early opening.", False),
        ("Permission is granted for evening use.", True),
        ("You can only enter with a day pass.", True),
    ]
    for text, expected in cases:
        assert psb.positive_permission_evidence(text)["found"] is expected, text


# ---------------------------------------------- composed scoring and metrics

def test_composed_verdict_priority():
    p1 = v3.compile_v3_structure({"modality": "PERMISSION", "relation": "IF",
                                  "target_clauses": [["action:x"]],
                                  "condition_literals": ["state:a"]})
    p2 = v3.compile_v3_structure({"modality": "PROHIBITION", "relation": "UNCONDITIONAL",
                                  "target_clauses": [["action:y"]]})
    assert psb.composed_verdict([p1, p2], {"action:x", "state:a"}) == "PERMITTED"
    assert psb.composed_verdict([p1, p2], {"action:x", "state:a", "action:y"}) == "VIOLATION"
    assert psb.composed_verdict([p1, p2], set()) == "NO_VIOLATION"
    assert psb.composed_verdict([], set()) == "NO_VIOLATION"
    # single-program composition equals the v3 verdict
    for facts in (set(), {"action:x"}, {"action:x", "state:a"}):
        assert psb.composed_verdict([p1], facts) == v3.evaluate_v3_program(p1, facts)


def test_canonical_triples_flat_matches_graph():
    cases = corpus.build_psb_causal_benchmark()
    checked = 0
    for case in cases:
        graph = case.gold_graph
        regulated = [n for n in graph["nodes"] if n["type"] == "REGULATED"]
        if len(regulated) != 1 or len(case.admissible_program_sets[0]) != 1:
            continue
        program = case.admissible_program_sets[0][0]
        assert psb.canonical_triples_flat(program) == \
            psb.canonical_triples_graph(graph), case.case_id
        checked += 1
    assert checked >= 25  # single-clause golds


def test_binding_metrics_math():
    gold = {("MODALITY", frozenset(["PERMISSION"]), frozenset(["action:x"])),
            ("CONDITION", frozenset(["state:a"]), frozenset(["action:x"]))}
    pred = {("MODALITY", frozenset(["PERMISSION"]), frozenset(["action:x"])),
            ("CONDITION", frozenset(["state:a"]), frozenset(["action:y"]))}
    metrics = psb.binding_metrics({"c": pred}, {"c": gold})
    assert metrics["per_class"]["MODALITY"]["f1"] == 1.0
    assert metrics["per_class"]["CONDITION"]["match"] == 0
    assert metrics["per_class"]["CONDITION"]["precision"] == 0.0
    assert metrics["per_class"]["CONDITION"]["recall"] == 0.0
    assert metrics["aggregate"]["n_gold"] == 2 and metrics["aggregate"]["n_pred"] == 2
    assert metrics["aggregate"]["match"] == 1
    assert round(metrics["aggregate"]["f1"], 4) == 0.5


def test_mcnemar_newcombe_wilson_known_values():
    assert runner.mcnemar_exact_p(0, 0) == 1.0
    assert round(runner.mcnemar_exact_p(10, 2), 6) == 0.038574
    assert runner.mcnemar_exact_p(5, 5) == 1.0
    lo, hi = runner.wilson_ci(59, 80)
    assert round(lo, 4) == 0.6318 and round(hi, 4) == 0.8214
    lo, hi = runner.newcombe_paired_ci(10, 2, 20)
    assert lo < 0.25 < hi  # delta 8/20 = 0.4 minus paired uncertainty
    assert 0 < lo < 0.4 < hi < 0.8


# ------------------------------------------------------------- pipeline test

@pytest.fixture()
def pipeline(tmp_path, monkeypatch):
    out = tmp_path / "psb_out"
    out.mkdir()
    assert runner.phase_freeze(REPO, out) == 0
    bench = json.loads((out / f"{runner.PREFIX}_benchmark.json").read_text())
    flat_by_policy, graph_by_policy = {}, {}
    for row in bench["cases"]:
        graph_by_policy[row["policy"]] = row["gold_graph"]
        programs = row["admissible_program_sets"][0]
        if programs:
            flat_by_policy[row["policy"]] = programs[0]
        else:  # empty-gold control: H0 must emit something (schema forces it)
            flat_by_policy[row["policy"]] = {
                "modality": "PERMISSION", "relation": "IF",
                "target_clauses": [[row["atom_catalog"][0]]],
                "condition_literals": [], "exception_literals": [],
                "condition_mode": "ALL", "exception_mode": "ALL",
                "temporal": "NONE", "actor": "assistant",
                "regulated_kind": "ACTION", "facet": "primary",
                "identity": "ANY", "provenance": "ANY", "quantification": "ALL"}
    FakeBackend.flat_by_policy = flat_by_policy
    FakeBackend.graph_by_policy = graph_by_policy
    FakeBackend.break_policy = bench["cases"][0]["policy"]
    monkeypatch.setattr(runner, "load_env_file", lambda path: None)
    monkeypatch.setattr(runner, "ChatClient", lambda config: None)
    monkeypatch.setattr(runner, "provider_config",
                        lambda config, backend, model=None: None)
    monkeypatch.setattr(runner, "DiagnosticSemanticBackend", FakeBackend)
    assert runner.phase_smoke(None, REPO, out) == 0
    assert runner.phase_run_h0(None, REPO, out, minutes=60) == 0
    assert runner.phase_run_psb(None, REPO, out, minutes=60) == 0
    assert runner.phase_score(REPO, out) == 0
    assert runner.phase_audit(REPO, out) == 0
    return out


def _expected_h0_correct():
    cases = corpus.build_psb_causal_benchmark()
    total = 0
    for case in cases:
        programs = list(case.admissible_program_sets[0])
        if not programs:
            stub = {"modality": "PERMISSION", "relation": "IF",
                    "target_clauses": [["action:bait_lobster_pots_early"]],
                    "condition_literals": [], "exception_literals": [],
                    "condition_mode": "ALL", "exception_mode": "ALL",
                    "temporal": "NONE", "actor": "assistant"}
            compiled = v3.compile_v3_structure(stub)
        else:
            compiled = v3.compile_v3_structure(_perturb_flat(dict(programs[0])))
        ok, _ = psb.score_program_set([compiled], case.worlds,
                                      case.admissible_program_sets)
        total += ok
    return total


def test_pipeline_measures_stub_behavior(pipeline):
    results = json.loads((pipeline / f"{runner.PREFIX}_results.json").read_text())
    cases = corpus.build_psb_causal_benchmark()
    expected_h0 = _expected_h0_correct()
    assert results["primary_metric"]["h0"]["correct"] == expected_h0
    # PSB stub answers with the exact gold graph: H1 = H2 = 44/44
    assert results["primary_metric"]["h1"]["correct"] == 44
    assert results["primary_metric"]["h2"]["correct"] == 44
    assert results["binding_attachment"]["psb_graph"]["aggregate"]["f1"] == 1.0
    # the gate never fires on gold-faithful permission clauses
    assert results["permission"]["h2"]["invented_permission_case_rate"] == 0.0
    assert results["permission"]["h2"]["permission_clause_precision"] == 1.0
    assert results["rejected_permission_clauses_h2"] == {}
    # verdict follows the frozen decision table from the stub measurements
    assert results["verdict"] in ("PROMOTE_TO_NEW_HOLDOUT",
                                  "HYPOTHESES_SUPPORTED_CANDIDATE_NOT_PROMOTED")
    h1_supported = results["h1_hypothesis_supported"]
    h2_supported = results["h2_hypothesis_supported"]
    primary = results["gates_evaluation"]["primary_candidate"]["pass"]
    assert results["verdict"] == ("PROMOTE_TO_NEW_HOLDOUT"
                                  if (h1_supported and h2_supported and primary)
                                  else "HYPOTHESES_SUPPORTED_CANDIDATE_NOT_PROMOTED")
    # repair path was exercised (first case forced INVALID then repaired)
    statuses = [row["status"] for row in json.loads(
        (pipeline / f"{runner.PREFIX}_h0_predictions.json").read_text())]
    assert statuses[0] == "ok_repaired"
    # paired statistics present for all three pairs
    for pair in ("h1_vs_h0", "h2_vs_h1", "h2_vs_h0"):
        entry = results["paired_statistics"][pair]
        assert {"corrections", "regressions", "mcnemar_exact_p_two_sided",
                "correction_precision"} <= set(entry)


def test_pipeline_seal_discipline_and_idempotence(pipeline):
    for arm in ("h0", "psb"):
        rows = json.loads(
            (pipeline / f"{runner.PREFIX}_{arm}_predictions.json").read_text())
        seal = json.loads(
            (pipeline / f"{runner.PREFIX}_{arm}_prediction_seal.json").read_text())
        assert seal["prediction_sha256"] == digest(rows)
        assert seal["gold_joined"] is False
    # reruns are byte-stable and refuse to double-run
    assert runner.phase_run_h0(None, REPO, pipeline, minutes=60) == 0
    assert runner.phase_score(REPO, pipeline) == 0
    assert runner.phase_audit(REPO, pipeline) == 0
    audit = json.loads((pipeline / f"{runner.PREFIX}_failure_audit.json").read_text())
    # only H0 has errors under the synthetic stubs (PSB answered with gold)
    assert audit["arms"]["h1"]["error_count"] == 0
    assert audit["arms"]["h2"]["error_count"] == 0
    assert audit["arms"]["h0"]["error_count"] == 44 - _expected_h0_correct()

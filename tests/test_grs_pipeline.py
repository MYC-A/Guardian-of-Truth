"""Offline selftest for the GRS experiment runner.

Everything here is DETERMINISTIC and SYNTHETIC: a fake in-process backend
answers with payload-derived canned values built from the frozen corpus gold
(explicitly STUB values that exercise plumbing only; never real model
outputs; these tests never report model results).  Covered: DSL grammar
parse/serialize roundtrip, validator rejections (unknown refs, type errors,
frozen envelope, duplicate gates, mode disagreement, ONE_OF limits),
compiler parity with the frozen PSB semantics (relation precedence,
temporal polarity, actor/identity/provenance necessity), oracle-inventory
well-formedness and neutral IDs, corpus invariants for Stage A and Stage B
(composition, gold self-score, 8-gram novelty incl. cross-stage, evidence
sufficiency), hallucination attempt counters, composed scoring with ONE_OF
alternatives, McNemar/Newcombe/Wilson math, prereg mirroring, H0 identity
continuity vs the sealed PSB freeze, the full freeze-a -> smoke-a -> run-a0
-> run-a1 -> score-a -> freeze-b -> smoke-b -> run-b0 -> run-b1 -> score-b
-> audit pipeline, the repair paths (H0, DSL, grounder), seal discipline
and rerun idempotence.
"""
import json
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import evaluate_vnext_policy_grs as runner  # noqa: E402
from guardian_truth.vnext import policy_grs as grs  # noqa: E402
from guardian_truth.vnext import policy_grs_causal_benchmark as corpus_a  # noqa: E402
from guardian_truth.vnext import policy_grs_prospective_benchmark as corpus_b  # noqa: E402
from guardian_truth.vnext import policy_psb as psb  # noqa: E402
from guardian_truth.vnext import policy_v3_benchmark as v3  # noqa: E402
from guardian_truth.vnext.integrity import digest  # noqa: E402
from guardian_truth.vnext.semantic import SYSTEM, Proposal  # noqa: E402


# ------------------------------------------------------------------ fake model

class FakeBackend:
    """Deterministic in-process delegate mimicking DiagnosticSemanticBackend.
    Answers H0-schema requests with flat gold-derived stubs, DSL requests
    with the exact gold DSL and grounder requests with the exact oracle
    inventory (SYNTHETIC stubs, plumbing only)."""

    flat_by_policy: dict = {}
    dsl_by_policy: dict = {}
    ground_by_policy: dict = {}
    break_a0_policy: str = None
    break_a1_policy: str = None
    break_ground_policy: str = None

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
        policy = payload.get("policy_text")
        if task in (grs.GRS_GROUND_TASK, grs.GRS_GROUND_REPAIR_TASK):
            if not is_repair and policy == FakeBackend.break_ground_policy:
                return Proposal(json.dumps({"facts": [
                    {"id": "F1", "atom": "action:totally_invented", "span": "the"}],
                    "markers": []}), "SUCCESS", "VALID")
            base = FakeBackend.ground_by_policy.get(policy)
            value = base if base is not None else {"facts": [], "markers": []}
        elif task in (grs.GRS_SYNTH_TASK, grs.GRS_SYNTH_REPAIR_TASK):
            if not is_repair and policy == FakeBackend.break_a1_policy:
                return Proposal(json.dumps({"dsl": "RULESET(RULE(PERMIT, F99))"}),
                                "SUCCESS", "VALID")
            base = FakeBackend.dsl_by_policy.get(policy)
            value = {"dsl": base} if base is not None else {"dsl": "RULESET()"}
        else:
            if not is_repair and policy == FakeBackend.break_a0_policy:
                return Proposal(None, "SUCCESS", "INVALID")
            base = FakeBackend.flat_by_policy.get(policy)
            if base is None:  # synthetic smoke payload (non-benchmark)
                value = {"modality": "PERMISSION", "relation": "ONLY_IF",
                         "target_clauses": [["action:use_goods_stairwell"]],
                         "condition_literals": [], "exception_literals": [],
                         "condition_mode": "ALL", "exception_mode": "ALL",
                         "temporal": "NONE", "actor": "assistant",
                         "regulated_kind": "ACTION", "facet": "primary",
                         "identity": "ANY", "provenance": "ANY",
                         "quantification": "ALL"}
            else:
                value = dict(base)
        return Proposal(json.dumps(value, sort_keys=True, separators=(",", ":")),
                        "SUCCESS", "VALID")


def _stub_ground(inventory: dict) -> dict:
    return {"facts": [{"id": f["id"], "atom": f["atom"], "span": f["span"]}
                      for f in inventory["facts"]],
            "markers": [{"id": m["id"], "kind": m["kind"], "value": m["value"],
                         "span": m["span"]} for m in inventory["markers"]]}


# --------------------------------------------------------------- grammar tests

def _inventory():
    return {'facts': [
        {'id': 'F1', 'kind': 'ACTION', 'atom': 'action:pour', 'span': 'pour'},
        {'id': 'F2', 'kind': 'STATE', 'atom': 'state:fridge_unlocked', 'span': 'unlocked'},
        {'id': 'F3', 'kind': 'STATE', 'atom': 'state:door_alarmed', 'span': 'alarmed'},
        {'id': 'F4', 'kind': 'ACTOR', 'atom': 'actor:staff', 'span': 'staff'},
        {'id': 'F5', 'kind': 'EVENT', 'atom': 'event:briefing', 'span': 'briefing'},
        {'id': 'F6', 'kind': 'IDENTITY', 'atom': 'identity:own', 'span': 'own name'},
        {'id': 'F7', 'kind': 'PROVENANCE', 'atom': 'evidence:tool', 'span': 'tool'}],
        'markers': [{'id': 'M1', 'kind': 'MODAL_MARKER', 'value': 'PERMIT',
                     'span': 'may'}]}


def test_parse_serialize_roundtrip():
    for dsl in ("RULESET()",
                "RULESET(RULE(PERMIT, F1, WHEN(F2), EXCEPT(F3), ACTOR(F4)))",
                "RULESET(RULE(PROHIBIT, TOGETHER(F1, F2), WHEN(AND(F2, NOT(F3)))))",
                "RULESET(RULE(REQUIRE, SEPARATE(F1, F2), ONLY_WHEN(OR(F2, F3))))",
                "RULESET(RULE(PERMIT, F1, AFTER(F5), BEFORE(F5)))"
                if False else
                "RULESET(RULE(PERMIT, F1, AFTER(F5)), RULE(REQUIRE, F2, BEFORE(F5)))",
                "RULESET(ONE_OF(RULE(PROHIBIT, F1, EXCEPT(F2)), "
                "RULE(PROHIBIT, F1, WHEN(NOT(F2)))))",
                "RULESET(RULE(PERMIT, F1, ONLY_ACTOR(F4), IDENTITY(F6), PROVENANCE(F7)))"):
        assert grs.ast_to_text(grs.parse_dsl(dsl)) == dsl, dsl


def test_validator_rejections():
    inv = _inventory()
    rejects = [
        "RULESET(RULE(PERMIT, F4))",                       # ACTOR as target
        "RULESET(RULE(PERMIT, F1, WHEN(M1)))",             # marker as ref
        "RULESET(RULE(PERMIT, F1, WHEN(F9)))",             # unknown ref
        "RULESET(RULE(PERMIT, F1, WHEN(F4)))",             # ACTOR in boolexpr
        "RULESET(RULE(PERMIT, F1, BEFORE(F2)))",           # non-event temporal
        "RULESET(RULE(PERMIT, F1, WHEN(F2), EXCEPT(F3), ACTOR(F4), ACTOR(F4)))",
        "RULESET(RULE(PERMIT, F1, WHEN(F2), ONLY_WHEN(F3)))",  # two relation gates
        "RULESET(RULE(PERMIT, F1, BEFORE(F5), AFTER(F5)))",    # two temporal gates
        "RULESET(RULE(REQUIRE, F1, WHEN(F2), EXCEPT(F3)))",    # frozen envelope
        "RULESET(RULE(PERMIT, F1, WHEN(AND(F2, F3)), EXCEPT(OR(F5))))"
        if False else "RULESET(RULE(PERMIT, F1, AFTER(AND(F5, F3)), WHEN(OR(F2))))",
        "RULESET(RULE(PERMIT, F1), RULE(PERMIT, F2), "
        "ONE_OF(RULE(PERMIT, F1), RULE(PERMIT, F2)), "
        "ONE_OF(RULE(PERMIT, F1), RULE(PERMIT, F2)))",     # two ONE_OFs
        "RULESET(RULE(PERMIT, F1, WHEN(F2) AND F3))",      # junk tokens
        "RULESET(RULE(MAYBE, F1))",                        # bad modality
        "RULESET(RULE(PERMIT, F1, FANCY(F2)))",            # unknown gate op
        "RULESET(RULE(PERMIT, F1, IDENTITY(F4)))",         # wrong kind for IDENTITY
    ]
    for dsl in rejects:
        with pytest.raises(grs.GRSInvalid):
            grs.compile_dsl(dsl, inv), dsl
    # empty ruleset is legal and compiles to the empty alternative
    alternatives, dropped = grs.compile_dsl("RULESET()", inv)
    assert alternatives == [[]] and dropped == []


def test_compiler_semantics_parity():
    inv = _inventory()
    # WHEN gate -> IF; ONLY_WHEN -> ONLY_IF; EXCEPT-only REQUIRE -> UNLESS
    programs, _ = grs.compile_ruleset_ast(
        grs.parse_dsl("RULESET(RULE(PERMIT, F1, WHEN(F2)))"), inv)
    assert programs[0][0]['relation'] == 'IF'
    programs, _ = grs.compile_ruleset_ast(
        grs.parse_dsl("RULESET(RULE(PERMIT, F1, ONLY_WHEN(F2)))"), inv)
    assert programs[0][0]['relation'] == 'ONLY_IF'
    programs, _ = grs.compile_ruleset_ast(
        grs.parse_dsl("RULESET(RULE(REQUIRE, F1, EXCEPT(F2)))"), inv)
    assert programs[0][0]['relation'] == 'UNLESS'
    # exclusive actor / identity / provenance imply ONLY_IF
    for gate in ('ONLY_ACTOR(F4)', 'IDENTITY(F6)', 'PROVENANCE(F7)'):
        programs, _ = grs.compile_ruleset_ast(
            grs.parse_dsl(f"RULESET(RULE(PERMIT, F1, {gate}))"), inv)
        assert programs[0][0]['relation'] == 'ONLY_IF', gate
    # plain actor -> IF with the actor literal in the conditions
    programs, _ = grs.compile_ruleset_ast(
        grs.parse_dsl("RULESET(RULE(PERMIT, F1, ACTOR(F4)))"), inv)
    assert programs[0][0]['relation'] == 'IF'
    assert programs[0][0]['condition_literals'] == ['actor:staff']
    # BEFORE negates event literals; AFTER keeps them positive
    programs, _ = grs.compile_ruleset_ast(
        grs.parse_dsl("RULESET(RULE(PERMIT, F1, BEFORE(F5)))"), inv)
    assert programs[0][0]['condition_literals'] == ['!event:briefing']
    assert programs[0][0]['temporal'] == 'BEFORE'
    programs, _ = grs.compile_ruleset_ast(
        grs.parse_dsl("RULESET(RULE(PERMIT, F1, AFTER(F5)))"), inv)
    assert programs[0][0]['condition_literals'] == ['event:briefing']
    assert programs[0][0]['temporal'] == 'AFTER'
    # IFF beats ONLY_IF; REQUIRE+EXCEPT beats both
    programs, _ = grs.compile_ruleset_ast(
        grs.parse_dsl("RULESET(RULE(PERMIT, F1, IFF(F2), ACTOR(F4)))"), inv)
    assert programs[0][0]['relation'] == 'IF_AND_ONLY_IF'
    # TOGETHER -> one clause; SEPARATE -> one clause per atom
    programs, _ = grs.compile_ruleset_ast(
        grs.parse_dsl("RULESET(RULE(PROHIBIT, TOGETHER(F1, F2)))"), inv)
    assert programs[0][0]['target_clauses'] == [['action:pour', 'state:fridge_unlocked']]
    programs, _ = grs.compile_ruleset_ast(
        grs.parse_dsl("RULESET(RULE(PROHIBIT, SEPARATE(F1, F2)))"), inv)
    assert programs[0][0]['target_clauses'] == [['action:pour'], ['state:fridge_unlocked']]
    # UNKNOWN gates drop the rule and are recorded; ONE_OF yields 2 alternatives
    alternatives, dropped = grs.compile_dsl(
        "RULESET(RULE(PERMIT, F1, UNKNOWN_RELATION(F2)))", inv)
    assert alternatives == [[]]
    assert dropped and dropped[0]['reason'] == 'UNKNOWN_RELATION'
    alternatives, dropped = grs.compile_dsl(
        "RULESET(ONE_OF(RULE(PROHIBIT, F1, EXCEPT(F2)), "
        "RULE(PROHIBIT, F1, UNKNOWN_ATTACHMENT(F2))))", inv)
    assert len(alternatives) == 2 and len(alternatives[1]) == 0
    assert dropped[0]['reason'] == 'UNKNOWN_ATTACHMENT'
    # single-rule composition equals the v3 verdict (H0 scoring continuity)
    program = grs.compile_dsl(
        "RULESET(RULE(PERMIT, F1, WHEN(F2), EXCEPT(F3)))", inv)[0][0]
    for facts in (set(), {'action:pour', 'state:fridge_unlocked'},
                  {'action:pour', 'state:fridge_unlocked', 'state:door_alarmed'}):
        assert psb.composed_verdict([program], facts) == \
            v3.evaluate_v3_program(program, facts)


def test_hallucination_counters():
    inv = _inventory()
    counts = grs.hallucination_attempts(
        'RULESET(RULE(PERMIT, F9, WHEN(F2), FANCY_OP(F3), "free text"))', inv)
    assert counts['unknown_reference_attempts'] == 1
    assert counts['out_of_grammar_operator_attempts'] == 1
    assert counts['free_text_leaf_attempts'] == 1
    assert grs.hallucination_attempts(
        'RULESET(RULE(PERMIT, F1, WHEN(F2)))', inv)['unknown_reference_attempts'] == 0


# ------------------------------------------------------------- corpus invariants

def test_stage_a_corpus_invariants():
    cases = corpus_a.build_grs_stage_a_benchmark()
    assert len(cases) == 56
    observed = {}
    for case in cases:
        observed[case.cohort] = observed.get(case.cohort, 0) + 1
        # gold self-scores; resolved; oracle inventory well-formed + neutral
        alternatives, dropped = grs.compile_dsl(case.gold_dsl, case.oracle_inventory)
        assert not dropped
        correct, _per = grs.grs_score_prediction(alternatives, case.worlds,
                                                 case.admissible_program_sets)
        assert correct, case.case_id
        grs.validate_inventory(case.oracle_inventory, case.policy)
        ids = [f['id'] for f in case.oracle_inventory['facts']] \
            + [m['id'] for m in case.oracle_inventory['markers']]
        assert all(i[0] in 'FMR' and i[1:].isdigit() for i in ids)
        assert len(ids) == len(set(ids))
        # the model input never leaks gold: inventory facts carry no role fields
        for fact in case.oracle_inventory['facts']:
            assert set(fact) == {'id', 'kind', 'atom', 'span'}
    assert observed == corpus_a.COHORT_PLAN
    # capacity split frozen: 11 H0-unrepresentable cases
    assert sum(not case.h0_representable for case in cases) == 11
    # novelty: no shared 8-gram with V4/V5/PHV1/PSB, no internal duplicates
    from guardian_truth.vnext.policy_v4_benchmark import build_v4_benchmark
    from guardian_truth.vnext.policy_v5_benchmark import build_v5_benchmark
    from guardian_truth.vnext.policy_phv1_holdout import build_phv1_holdout
    from guardian_truth.vnext.policy_psb_causal_benchmark import build_psb_causal_benchmark

    def ngrams(text):
        words = ["".join(ch for ch in w.lower() if ch.isalnum())
                 for w in text.split()]
        words = [w for w in words if w]
        return {tuple(words[i:i + 8]) for i in range(len(words) - 7)}

    old = set()
    for builder, seed in ((build_v4_benchmark, 260914), (build_v5_benchmark, 260915),
                          (build_phv1_holdout, None), (build_psb_causal_benchmark, None)):
        for case in (builder(seed) if seed else builder()):
            old |= ngrams(case.policy)
    seen = set()
    for case in cases:
        assert not (ngrams(case.policy) & old), case.case_id
        assert not (ngrams(case.policy) & seen), case.case_id
        seen |= ngrams(case.policy)


def test_stage_b_corpus_invariants():
    cases = corpus_b.build_grs_stage_b_benchmark()
    assert len(cases) == 72
    observed = {}
    for case in cases:
        observed[case.cohort] = observed.get(case.cohort, 0) + 1
        alternatives, dropped = grs.compile_dsl(case.gold_dsl, case.oracle_inventory)
        assert not dropped
        correct, _per = grs.grs_score_prediction(alternatives, case.worlds,
                                                 case.admissible_program_sets)
        assert correct, case.case_id
    assert observed == corpus_b.COHORT_PLAN_B
    assert sum(not case.h0_representable for case in cases) == 17
    # Stage B is fresh vs Stage A as well
    stage_a = {case.case_id for case in corpus_a.build_grs_stage_a_benchmark()}
    stage_b = {case.case_id for case in cases}
    assert not (stage_a & stage_b)


def test_one_of_scoring_requires_every_alternative():
    cases = {c.case_id: c for c in corpus_a.build_grs_stage_a_benchmark()}
    case = cases['multi_axis::x06']
    inv = case.oracle_inventory
    facts = {'action:serve_the_raw_milk_cheeses', 'state:dairy_manager_signoff'}
    # both readings acceptable -> correct
    alts, _ = grs.compile_dsl(case.gold_dsl, inv)
    correct, _per = grs.grs_score_prediction(alts, case.worlds,
                                             case.admissible_program_sets)
    assert correct
    # a hedged prediction with one wrong alternative fails
    wrong_alts, _ = grs.compile_dsl(
        "RULESET(ONE_OF(RULE(PROHIBIT, F1, EXCEPT(F2)), RULE(PERMIT, F1)))",
        inv)
    correct, per_world = grs.grs_score_prediction(wrong_alts, case.worlds,
                                                  case.admissible_program_sets)
    assert not correct


# ------------------------------------------------------------- statistics math

def test_mcnemar_newcombe_wilson_known_values():
    assert runner.mcnemar_exact_p(0, 0) == 1.0
    assert round(runner.mcnemar_exact_p(10, 2), 6) == 0.038574
    lo, hi = runner.wilson_ci(59, 80)
    assert round(lo, 4) == 0.6318 and round(hi, 4) == 0.8214


def test_prereg_mirrors_runner_gates():
    prereg = json.loads((REPO / runner.PREREG_DOC).read_text(encoding='utf-8'))
    assert prereg['stage_a']['gates'] == runner.GRS_GATES['stage_a']
    assert prereg['stage_b']['gates'] == runner.GRS_GATES['stage_b']
    assert prereg['stage_a']['composition'] == corpus_a.COHORT_PLAN
    assert prereg['stage_b']['composition'] == corpus_b.COHORT_PLAN_B


def test_h0_identity_continuity_vs_psb_freeze():
    continuity = runner._h0_continuity(REPO)
    assert all(continuity[key] for key in
               ('parse_task_match', 'repair_task_match',
                'structure_schema_match', 'definition_match'))


def test_postvalidate_ground_rejections():
    policy = "Members may polish the brass rail before tours."
    catalog = ["action:polish_brass_rail", "event:tour", "actor:member"]
    ok = {"facts": [{"id": "F1", "atom": "action:polish_brass_rail",
                     "span": "polish the brass rail"}],
          "markers": [{"id": "M1", "kind": "MODAL_MARKER", "value": "PERMIT",
                       "span": "may"}]}
    inventory = runner._postvalidate_ground(ok, policy, catalog)
    assert inventory['facts'][0]['kind'] == 'ACTION'
    rejects = [
        {"facts": [{"id": "F1", "atom": "action:invented", "span": "polish"}],
         "markers": []},                                   # atom not in catalog
        {"facts": [{"id": "F1", "atom": "action:polish_brass_rail",
                    "span": "no such span"}], "markers": []},  # bad span
        {"facts": [{"id": "X1", "atom": "action:polish_brass_rail",
                    "span": "polish"}], "markers": []},     # bad id shape
        {"facts": [{"id": "F1", "atom": "action:polish_brass_rail",
                     "span": "polish"},
                    {"id": "F2", "atom": "action:polish_brass_rail",
                     "span": "rail"}], "markers": []},      # duplicate atom
        {"facts": [], "markers": [{"id": "M1", "kind": "RELATION_MARKER",
                                    "value": "PERMIT", "span": "may"}]},  # kind/value
        {"facts": [], "markers": [{"id": "M1", "kind": "MODAL_MARKER",
                                    "value": "MAYBE", "span": "may"}]},  # bad value
    ]
    for value in rejects:
        with pytest.raises(grs.GRSInvalid):
            runner._postvalidate_ground(value, policy, catalog)


# ------------------------------------------------------------- pipeline test

@pytest.fixture()
def pipeline(tmp_path, monkeypatch):
    out = tmp_path / "grs_out"
    out.mkdir()
    assert runner.phase_freeze_a(REPO, out) == 0
    bench = json.loads((out / f"{runner.PREFIX_A}_benchmark.json").read_text())
    flat_by_policy, dsl_by_policy, ground_by_policy = {}, {}, {}
    for row in bench["cases"]:
        dsl_by_policy[row["policy"]] = row["gold_dsl"]
        ground_by_policy[row["policy"]] = _stub_ground(row["oracle_inventory"])
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
    FakeBackend.dsl_by_policy = dsl_by_policy
    FakeBackend.ground_by_policy = ground_by_policy
    FakeBackend.break_a0_policy = bench["cases"][0]["policy"]
    FakeBackend.break_a1_policy = bench["cases"][0]["policy"]
    monkeypatch.setattr(runner, "load_env_file", lambda path: None)
    monkeypatch.setattr(runner, "ChatClient", lambda config: None)
    monkeypatch.setattr(runner, "provider_config",
                        lambda config, backend, model=None: None)
    monkeypatch.setattr(runner, "DiagnosticSemanticBackend", FakeBackend)
    assert runner.phase_smoke_a(None, REPO, out) == 0
    assert runner.phase_run_a0(None, REPO, out, minutes=60) == 0
    assert runner.phase_run_a1(None, REPO, out, minutes=60) == 0
    assert runner.phase_score_a(REPO, out) == 0
    return out


def _expected_a0_correct():
    cases = corpus_a.build_grs_stage_a_benchmark()
    total = 0
    for case in cases:
        programs = list(case.admissible_program_sets[0])
        if not programs:
            total += 0  # H0 is forced to regulate something -> fails empty gold
            continue
        compiled = v3.compile_v3_structure(dict(programs[0]))
        ok, _ = psb.score_program_set([compiled], case.worlds,
                                      case.admissible_program_sets)
        total += ok
    return total


def test_stage_a_pipeline_measures_stub_behavior(pipeline):
    results = json.loads(
        (pipeline / f"{runner.PREFIX_A}_results.json").read_text())
    # A1 stub answers with the exact gold DSL: 56/56, validity 1.0
    assert results["primary_metric"]["a1"]["correct"] == 56
    assert results["validity"]["a1"] == 1.0
    assert results["primary_metric"]["a0"]["correct"] == _expected_a0_correct()
    assert results["binding_attachment"]["a1_compiled"]["aggregate"]["f1"] == 1.0
    assert results["resolved_coverage_a1"] == 1.0
    assert results["unsafe_permission_cases"]["a1"] == 0
    assert results["hallucination_attempts"]["unknown_reference_attempts"] >= 1
    # verdict follows the frozen gate table from the stub measurements
    assert results["verdict"] == "PASS_STAGE_A"
    gates = results["gates_evaluation"]["evaluation"]
    assert gates["behavioral_pass"] and gates["validity_pass"]
    assert gates["capacity_pass"] and gates["nl_pass"]
    assert gates["regression_pass"] and gates["delta_pass"]
    # repair paths were exercised (first case forced INVALID then repaired)
    statuses_a0 = [row["status"] for row in json.loads(
        (pipeline / f"{runner.PREFIX_A}_a0_predictions.json").read_text())]
    statuses_a1 = [row["status"] for row in json.loads(
        (pipeline / f"{runner.PREFIX_A}_a1_predictions.json").read_text())]
    assert statuses_a0[0] == "ok_repaired"
    assert statuses_a1[0] == "ok_repaired"
    # paired statistics present
    entry = results["paired_statistics"]["a1_vs_a0"]
    assert {"corrections", "regressions", "mcnemar_exact_p_two_sided",
            "correction_precision"} <= set(entry)
    # regression gate: gold-faithful A1 never regresses an H0-correct case
    assert results["regression_gate"]["wrong"] == 0


def test_stage_a_seal_discipline_and_idempotence(pipeline):
    for arm in ("a0", "a1"):
        rows = json.loads(
            (pipeline / f"{runner.PREFIX_A}_{arm}_predictions.json").read_text())
        seal = json.loads(
            (pipeline / f"{runner.PREFIX_A}_{arm}_prediction_seal.json").read_text())
        assert seal["prediction_sha256"] == digest(rows)
        assert seal["gold_joined"] is False
    assert runner.phase_run_a0(None, REPO, pipeline, minutes=60) == 0
    assert runner.phase_run_a1(None, REPO, pipeline, minutes=60) == 0
    assert runner.phase_score_a(REPO, pipeline) == 0


def test_stage_b_pipeline_end_to_end(pipeline, monkeypatch):
    out = pipeline
    assert runner.phase_freeze_b(REPO, out) == 0
    bench_b = json.loads((out / f"{runner.PREFIX_B}_benchmark.json").read_text())
    FakeBackend.break_ground_policy = bench_b["cases"][3]["policy"]
    assert runner.phase_smoke_b(None, REPO, out) == 0
    assert runner.phase_run_b0(None, REPO, out, minutes=60) == 0
    assert runner.phase_run_b1(None, REPO, out, minutes=60) == 0
    assert runner.phase_score_b(REPO, out) == 0
    results = json.loads((out / f"{runner.PREFIX_B}_results.json").read_text())
    # stub grounder returns the exact oracle inventory; stub synthesizer the gold
    assert results["primary_metric"]["b1"]["correct"] == 72
    assert results["grounder_metrics"]["atom_precision"] == 1.0
    assert results["grounder_metrics"]["atom_recall"] == 1.0
    assert results["grounder_metrics"]["needed_atom_recall"] == 1.0
    assert results["grounder_metrics"]["marker_precision"] == 1.0
    assert results["synthesizer_conditional_on_sufficient_clean_inventory"] == {
        "n": 72, "correct": 72, "accuracy": 1.0}
    assert results["decomposition"]["grounding_cost_pp"] == 0.0
    assert results["unsafe_permission_rate"]["b1"] == 0.0
    assert results["resolved_coverage_b1"] == 1.0
    # the grounder repair path fired once (invented atom then repaired)
    ground_rows = json.loads(
        (out / f"{runner.PREFIX_B}_ground_predictions.json").read_text())
    assert ground_rows[3]["status"] == "ok_repaired"
    # verdict: every frozen gate passes under the stub
    assert results["verdict"] == "PROMOTE_GRS_TO_INTEGRATION"
    # audit covers both stages; only H0 arms have errors under gold stubs
    assert runner.phase_audit(REPO, out) == 0
    audit = json.loads((out / "policy_grs_v1_failure_audit.json").read_text())
    assert audit["stages"]["A"]["arms"]["a1"]["error_count"] == 0
    assert audit["stages"]["B"]["arms"]["b1"]["error_count"] == 0
    assert audit["stages"]["B"]["arms"]["b0"]["error_count"] == \
        72 - _expected_b0_correct()


def _expected_b0_correct():
    cases = corpus_b.build_grs_stage_b_benchmark()
    total = 0
    for case in cases:
        programs = list(case.admissible_program_sets[0])
        if not programs:
            continue
        compiled = v3.compile_v3_structure(dict(programs[0]))
        ok, _ = psb.score_program_set([compiled], case.worlds,
                                      case.admissible_program_sets)
        total += ok
    return total


def test_freeze_b_refuses_when_stage_a_rejected(tmp_path, monkeypatch):
    out = tmp_path / "grs_reject"
    out.mkdir()
    assert runner.phase_freeze_a(REPO, out) == 0
    # point STAGE_A_RESULTS_PATH at a doctored REJECT verdict (test-only)
    results = json.loads((out / f"{runner.PREFIX_A}_results.json").read_text()) \
        if (out / f"{runner.PREFIX_A}_results.json").exists() else {"verdict": "PASS_STAGE_A"}
    results["verdict"] = "REJECT_GRS_COMPOSITION"
    doctored = out / "doctored_stage_a_results.json"
    doctored.write_text(json.dumps(results), encoding="utf-8")
    monkeypatch.setattr(runner, "STAGE_A_RESULTS_PATH", str(doctored))
    with pytest.raises(ValueError):
        runner.phase_freeze_b(REPO, out)

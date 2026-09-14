"""Selftest for the policy_v3_benchmark reimplementation semantics and the
recovered V5 benchmark under the C-ALR reimplementation study.

All checks are deterministic (no LLM, no network). Fixtures are the REAL
recovered benchmark templates (policy_v5_benchmark.py, verbatim recovered
source) — these tests validate the engine, never report model results.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from guardian_truth.vnext import policy_v3_benchmark as v3
from guardian_truth.vnext import policy_v5_benchmark as v5


def _cases():
    return v5.build_v5_benchmark(seed=260915)


def _accepting_worlds(case):
    return v3.case_world_acceptance(case.worlds)


def test_benchmark_counts_and_shapes():
    cases = _cases()
    assert len(cases) == 142
    unamb = [c for c in cases if not c.ambiguous]
    amb = [c for c in cases if c.ambiguous]
    assert len(unamb) == 94 and len(amb) == 48
    traps = [c for c in cases if c.trap]
    assert len(traps) == 62
    assert all(not (c.trap and c.ambiguous) for c in cases)
    ids = [c.case_id for c in cases]
    assert len(set(ids)) == 142
    # every case carries compiled gold programs and a non-empty world surface
    for case in cases:
        assert case.admissible_programs and case.worlds
        for program in case.admissible_programs:
            assert program["modality"] in v3.MODALITIES
        merged = _accepting_worlds(case)
        assert merged
    # ambiguous cases: at least one world with two acceptable verdicts
    for case in amb:
        merged = _accepting_worlds(case)
        assert any(len(e["acceptable"]) == 2 for e in merged.values()), case.case_id
    # unambiguous cases: every world accepts exactly one verdict
    for case in unamb:
        merged = _accepting_worlds(case)
        assert all(len(e["acceptable"]) == 1 for e in merged.values()), case.case_id


def test_gold_tautology_both_readings():
    # the engine must accept both admissible readings of every ambiguous case
    for case in _cases():
        for structure in case.admissible_structures:
            ok, per_world, program = v3.score_candidate_structure(
                dict(structure), case.worlds, case.admissible_programs)
            assert ok, f"{case.case_id}: gold structure scored wrong: {per_world[:2]}"
            assert program is not None


def test_trap_flip_sensitivity():
    # applying the catalog mutations to the GOLD structure of unambiguous
    # cases must change the behavioral outcome on at least one world for the
    # relation / coordination / scope / actor axes (the v5 trap design).
    # NOTE: relation flips are behaviorally inert on PROHIBITION (IF and
    # ONLY_IF verdicts coincide by the declared static-world semantics), so
    # the per-case sensitivity assertion is restricted to TRAP cases, which
    # the v5 design guarantees to carry a load-bearing axis; the aggregate
    # threshold below covers all unambiguous cases.
    insensitive_families = set()
    flipped = 0
    for case in _cases():
        if case.ambiguous:
            continue
        program = v3.compile_v3_structure(dict(case.admissible_structures[0]))
        proposals = v3.propose_mutations(program)
        behavioral = [p for p in proposals
                      if p["mutation_type"] not in ("TEMPORAL_BEFORE_TO_AFTER",
                                                    "TEMPORAL_AFTER_TO_BEFORE")]
        if not behavioral:
            insensitive_families.add(case.family)
            continue
        if case.trap:
            any_flip = any(
                not v3.score_candidate_structure(
                    v3.apply_patch(program, p["patch"]), case.worlds,
                    case.admissible_programs)[0]
                for p in behavioral)
            assert any_flip, f"{case.case_id}: no proposal changes the gold outcome"
        else:
            any_flip = any(
                not v3.score_candidate_structure(
                    v3.apply_patch(program, p["patch"]), case.worlds,
                    case.admissible_programs)[0]
                for p in behavioral)
        if any_flip:
            flipped += 1
    # only genuinely mutation-free or catalog-inert families may be skipped
    # (e.g. bare state requirements; single-condition PROHIBITION whose only
    # proposals are relation flips); the trap families must all be sensitive
    assert flipped >= 60


def test_prohibition_relation_flips_inert():
    # declared-semantics regression guard: for PROHIBITION the IF / ONLY_IF /
    # IF_AND_ONLY_IF relations coincide on every world (no exclusivity axis),
    # so relation mutations must not be proposed as behaviorally load-bearing
    # anywhere; PERMISSION exclusivity stays the only relation-sensitive
    # modality. This is why trap sensitivity excludes non-trap single-condition
    # prohibitions such as stress_nested_clause::snc2.
    prog = {"modality": "PROHIBITION", "relation": "IF",
            "target_clauses": [["action:a"]], "condition_literals": ["state:c"],
            "exception_literals": [], "condition_mode": "ALL",
            "exception_mode": "ALL", "temporal": "NONE", "actor": "assistant",
            "regulated_kind": "ACTION", "facet": "primary", "identity": "ANY",
            "provenance": "ANY", "quantification": "ALL"}
    base = v3.evaluate_v3_program(prog, {"action:a", "state:c"})
    for rel in ("ONLY_IF", "IF_AND_ONLY_IF"):
        flipped = dict(prog, relation=rel)
        assert v3.evaluate_v3_program(flipped, {"action:a", "state:c"}) == base
        assert v3.evaluate_v3_program(flipped, {"action:a"}) == v3.evaluate_v3_program(prog, {"action:a"})


def test_propose_mutations_deterministic_and_cataloged():
    cases = _cases()
    program = v3.compile_v3_structure(dict(cases[0].admissible_structures[0]))
    p1 = v3.propose_mutations(program)
    p2 = v3.propose_mutations(v3.compile_v3_structure(dict(cases[0].admissible_structures[0])))
    assert p1 == p2
    assert all(p["mutation_type"] in v3.MUTATION_CATALOG_V1 for p in p1)
    # together-clause case proposes merge->split; separate proposes split->merge
    together = next(c for c in cases if c.case_id.startswith("trap_scope::ts1"))
    prog = v3.compile_v3_structure(dict(together.admissible_structures[0]))
    types = [p["mutation_type"] for p in v3.propose_mutations(prog)]
    assert "CLAUSE_MERGE_TO_SPLIT" in types
    separate = next(c for c in cases if c.case_id.startswith("ambiguous_scope::asc1"))
    prog = v3.compile_v3_structure(dict(separate.admissible_structures[1]))  # separate reading
    types = [p["mutation_type"] for p in v3.propose_mutations(prog)]
    assert "CLAUSE_SPLIT_TO_MERGE" in types
    # ANY-mode two-condition case proposes the mode flip
    anycase = next(c for c in cases if c.case_id.startswith("trap_and_or::to5"))
    prog = v3.compile_v3_structure(dict(anycase.admissible_structures[0]))
    types = [p["mutation_type"] for p in v3.propose_mutations(prog)]
    assert "COND_ANY_TO_ALL" in types


def test_span_grounding_checks():
    text = "You may renew the berth licence only while the marina office is open."
    assert v3.span_is_verbatim("only while the marina office is open", text)
    assert v3.span_is_verbatim("  only   while the\nmarina office is open. ", text)
    assert not v3.span_is_verbatim("only when the marina office is open", text)
    assert not v3.span_is_verbatim("", text)
    assert not v3.span_is_verbatim(None, text)
    assert not v3.span_is_verbatim("marina office", "")


def test_permission_invariant_and_specific_verdicts():
    def prog(**kw):
        base = {"modality": "PERMISSION", "relation": "IF",
                "target_clauses": [["action:a"]], "condition_literals": ["state:c"],
                "exception_literals": [], "condition_mode": "ALL",
                "exception_mode": "ALL", "temporal": "NONE", "actor": "assistant",
                "regulated_kind": "ACTION", "facet": "primary", "identity": "ANY",
                "provenance": "ANY", "quantification": "ALL"}
        base.update(kw)
        return base

    # bare permission: acting without the condition is NOT a violation (silence)
    assert v3.evaluate_v3_program(prog(relation="IF"), {"action:a"}) == "NO_VIOLATION"
    assert v3.evaluate_v3_program(prog(relation="IF"), {"action:a", "state:c"}) == "PERMITTED"
    # exclusive permission: acting without the condition violates
    assert v3.evaluate_v3_program(prog(relation="ONLY_IF"), {"action:a"}) == "VIOLATION"
    assert v3.evaluate_v3_program(prog(relation="ONLY_IF"), {"action:a", "state:c"}) == "PERMITTED"
    # iff behaves like ONLY_IF on the negative side
    assert v3.evaluate_v3_program(prog(relation="IF_AND_ONLY_IF"), {"action:a"}) == "VIOLATION"
    # prohibition unless: exception grants explicit PERMITTED
    p = prog(modality="PROHIBITION", relation="UNLESS", condition_literals=[],
             exception_literals=["state:e"])
    assert v3.evaluate_v3_program(p, {"action:a"}) == "VIOLATION"
    assert v3.evaluate_v3_program(p, {"action:a", "state:e"}) == "PERMITTED"
    assert v3.evaluate_v3_program(p, set()) == "NO_VIOLATION"
    # requirement if: unmet obligation under condition
    r = prog(modality="REQUIREMENT", relation="IF")
    assert v3.evaluate_v3_program(r, {"state:c"}) == "VIOLATION"
    assert v3.evaluate_v3_program(r, {"state:c", "action:a"}) == "NO_VIOLATION"
    assert v3.evaluate_v3_program(r, set()) == "NO_VIOLATION"
    # together vs separate scope
    together = prog(modality="PROHIBITION", relation="UNCONDITIONAL",
                    target_clauses=[["action:x", "action:y"]], condition_literals=[])
    separate = prog(modality="PROHIBITION", relation="UNCONDITIONAL",
                    target_clauses=[["action:x"], ["action:y"]], condition_literals=[])
    assert v3.evaluate_v3_program(together, {"action:x"}) == "NO_VIOLATION"
    assert v3.evaluate_v3_program(separate, {"action:x"}) == "VIOLATION"
    assert v3.evaluate_v3_program(together, {"action:x", "action:y"}) == "VIOLATION"


def test_distinguishing_world_finds_all_ambiguous_pairs():
    for case in _cases():
        if not case.ambiguous:
            continue
        a, b = case.admissible_programs[0], case.admissible_programs[1]
        pair = v3._distinguishing_world(a, b, list(case.atom_catalog))
        assert pair is not None, f"{case.case_id}: readings not distinguishable"
        facts, va, vb = pair
        assert va != vb


def test_benchmark_document_deterministic():
    doc1 = v5.benchmark_v5_document(_cases())
    doc2 = v5.benchmark_v5_document(_cases())
    assert doc1["cases_sha256"] == doc2["cases_sha256"]
    assert doc1["frozen_before_predictions"] is True
    assert len(doc1["cases"]) == 142
    # models never see labels: the document carries them, the runner will not
    blob = json.dumps(doc1)
    assert "expected" in blob  # worlds carry expected verdicts (gold side)

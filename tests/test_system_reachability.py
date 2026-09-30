"""Adversarial controls for local reachability and refusal decisions."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.integration.contracts import facts_from_documented
from guardian_truth.integration.proof_engine import ReviewedProgram
from guardian_truth.integration.reachability import (
    ReviewedGoal, assess_local_reachability, decide_refusal)
from guardian_truth.step2.verifier import CallEvent, ResultEvent, TrajectoryCase

DATA = (ROOT / "experiments/searh_23/system_integration_v1/frozen/refusal_v1"
        / "dev_inputs.json")


def _setup(case_id):
    row = next(x for x in json.loads(DATA.read_text(encoding="utf-8"))
               if x["case_id"] == case_id)
    calls = tuple(CallEvent(e["index"], e["call_id"], e["tool"], e["arguments"])
                  for e in row["history"] if e["role"] == "assistant" and "tool" in e)
    results = tuple(ResultEvent(e["index"], e["call_id"], e["tool"], e["payload"])
                    for e in row["history"] if e["role"] == "tool")
    case = TrajectoryCase(case_id, row["system_policy"], "control",
                          tuple(row["available_tools"]), calls, results)
    raw = row["reviewed_goal"]
    goal = ReviewedGoal(raw["quote"], raw["entity_type"], raw["entity_id"],
                        raw["predicate"], raw["value"],
                        raw["candidate_actions_exhaustive"],
                        tuple(raw["candidate_calls"]), raw["evidence_source"])
    programs = tuple(ReviewedProgram(**p) for p in row["reviewed_policy_programs"])
    facts, _, _ = facts_from_documented(case)
    return row, case, goal, programs, tuple(facts)


def _reach(row, case, goal, programs, facts, *, catalog_complete=True):
    return assess_local_reachability(
        row["user_request"], row["target_response"]["text"],
        row["target_response"]["index"], goal, programs, case, facts,
        catalog_complete=catalog_complete)


def test_hypothetical_next_call_never_becomes_observed_action_or_fact():
    row, case, goal, programs, facts = _setup("library.ready")
    before_calls, before_results, before_facts = case.calls, case.results, facts
    proof = _reach(row, case, goal, programs, facts)
    assert proof["status"] == "REACHABLE"
    assert proof["plans"][0]["policy_proofs"][0]["hypothetical"] is True
    assert case.calls == before_calls and case.results == before_results
    assert facts == before_facts


def test_catalog_and_goal_completeness_are_required_for_closed_world():
    row, case, goal, programs, facts = _setup("library.no_capability")
    assert _reach(row, case, goal, programs, facts)["status"] == "CLOSED"
    assert _reach(row, case, goal, programs, facts,
                  catalog_complete=False)["status"] == "UNKNOWN"
    incomplete = replace(goal, candidate_actions_exhaustive=False)
    assert _reach(row, case, incomplete, programs, facts)["status"] == "UNKNOWN"


def test_false_tool_effect_or_unstated_plan_argument_cannot_prove_path():
    row, case, goal, programs, facts = _setup("warehouse.restored")
    assert _reach(row, case, goal, programs, facts)["status"] == "REACHABLE"
    original = goal.candidate_calls[0]
    wrong = replace(goal, candidate_calls=({**original, "arguments": {
        **original["arguments"], "quantity": 70}},))
    proof = _reach(row, case, wrong, programs, facts)
    assert proof["status"] == "UNKNOWN"
    assert proof["plans"][0]["reason"] == "plan_argument_not_in_user_goal"
    tool = dict(case.tools[-1])
    contract = dict(tool["documented_contracts"][0])
    contract["strength"] = "REQUESTED"
    tool["documented_contracts"] = [contract]
    altered = replace(case, tools=case.tools[:-1] + (tool,))
    proof = _reach(row, altered, goal, programs, facts)
    assert proof["status"] == "UNKNOWN"
    assert proof["plans"][0]["reason"] == "goal_effect_contract_unproven"


def test_open_is_not_a_proven_false_refusal():
    row, case, goal, programs, facts = _setup("library.checkable")
    reach = _reach(row, case, goal, programs, facts)
    assert reach["status"] == "OPEN"
    assert reach["plans"][0]["checking_actions"]
    verdict = decide_refusal(row["target_response"]["text"],
                             row["reviewed_refusal"], reach)
    assert verdict["status"] == "UNKNOWN"


def test_refusal_interpretation_must_be_source_exact():
    row, case, goal, programs, facts = _setup("library.ready")
    reach = _reach(row, case, goal, programs, facts)
    bad = dict(row["reviewed_refusal"])
    bad["quote"] = "The agent refuses."
    assert decide_refusal(row["target_response"]["text"], bad, reach)["status"] == "UNKNOWN"

"""Counterfactual proof checks across policy, world facts and claims.

The reviewed programs are deliberately oracle inputs. These controls test
whether the runtime can misuse time, scope, actor attribution or exceptions.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardian_truth.integration.contracts import facts_from_documented
from guardian_truth.integration.proof_engine import (
    ClaimQuery, check_call, check_claim, decide_reviewed, load_reviewed_programs)
from guardian_truth.step2.verifier import CallEvent, ResultEvent, TrajectoryCase

FROZEN = ROOT / "experiments/searh_23/system_integration_v1/frozen/trajectories_v1"
PROGRAMS = (ROOT / "experiments/searh_23/system_integration_v1"
            / "reviewed_policy_programs_dev.json")


def _fixture(case_id: str):
    rows = json.loads((FROZEN / "dev_inputs.json").read_text(encoding="utf-8"))
    row = next(row for row in rows if row["case_id"] == case_id)
    calls = tuple(CallEvent(e["index"], e["call_id"], e["tool"], e["arguments"])
                  for e in row["history"] if e["role"] == "assistant" and "tool" in e)
    results = tuple(ResultEvent(e["index"], e["call_id"], e["tool"], e["payload"])
                    for e in row["history"] if e["role"] == "tool")
    case = TrajectoryCase(case_id, row["system_policy"], "reviewed_control",
                          tuple(row["available_tools"]), calls, results)
    program = next(p for p in load_reviewed_programs(PROGRAMS) if p.policy == row["system_policy"])
    return row, case, program


def _facts(case):
    facts, _, issues = facts_from_documented(case)
    assert not issues
    return tuple(facts)


def test_later_approval_cannot_justify_earlier_action():
    _, case, program = _fixture("depot.success")
    target = next(c for c in case.calls if c.tool == program.governed_tool)
    assert check_call(program, case, target, _facts(case))["status"] == "SATISFIED"
    inspect = next(c for c in case.calls if c.tool != program.governed_tool)
    later_call = replace(inspect, index=target.index + 2)
    later_result = replace(next(r for r in case.results if r.call_id == inspect.call_id),
                           index=target.index + 3)
    changed = replace(case,
                      calls=tuple(later_call if c == inspect else c for c in case.calls),
                      results=tuple(later_result if r.call_id == inspect.call_id else r
                                    for r in case.results))
    proof = check_call(program, changed, target, _facts(changed))
    assert proof["status"] == "UNKNOWN"
    assert proof["reason"] == "no_prior_scoped_fact"


def test_amount_mismatch_never_uses_same_order_approval():
    _, case, program = _fixture("payments.approved")
    target = next(c for c in case.calls if c.tool == program.governed_tool)
    approval = next(c for c in case.calls if c.tool == "read_approval")
    changed_approval = replace(approval, payload={**approval.payload, "amount": 100})
    changed = replace(case, calls=tuple(changed_approval if c == approval else c
                                        for c in case.calls))
    proof = check_call(program, changed, target, _facts(changed))
    assert proof["status"] == "UNKNOWN"


def test_stale_tool_catalog_invalidates_reviewed_action_scope():
    _, case, program = _fixture("depot.success")
    target = next(c for c in case.calls if c.tool == program.governed_tool)
    catalog = list(case.tools)
    changed_tool = dict(catalog[1])
    changed_tool["result_schema"] = {**changed_tool["result_schema"],
                                      "unrelated_new_field": "string"}
    catalog[1] = changed_tool
    changed = replace(case, tools=tuple(catalog))
    proof = check_call(program, changed, target, _facts(changed))
    assert proof["status"] == "UNKNOWN"
    assert proof["reason"] == "governed_producer_unverified"


def test_emergency_exception_cannot_waive_other_condition():
    _, safe, program = _fixture("records.emergency_exception")
    target_safe = next(c for c in safe.calls if c.tool == program.governed_tool)
    assert check_call(program, safe, target_safe, _facts(safe))["status"] == "SATISFIED"
    _, denied, program = _fixture("records.exception_identity_denied")
    target_denied = next(c for c in denied.calls if c.tool == program.governed_tool)
    proof = check_call(program, denied, target_denied, _facts(denied))
    assert proof["status"] == "VIOLATION"
    assert proof["reason"] == "all"


def test_read_state_does_not_prove_assistant_caused_it():
    row, case, _ = _fixture("depot.timeout_confirmed")
    facts = _facts(case)
    response = "I dispatched parcel P-41."
    claim = ClaimQuery(response, row["target_response"]["index"], response,
                       0, len(response), "CLAIMED_COMPLETED",
                       "parcel.dispatch_state", "parcel", "P-41", "dispatched",
                       "HUMAN_REVIEWED", "ASSISTANT")
    proof = check_claim(claim, facts)
    assert proof["status"] == "UNKNOWN"
    assert proof["reason"] == "assistant_effect_unproven"
    state = replace(claim, actor="UNSPECIFIED")
    assert check_claim(state, facts)["status"] == "SUPPORTED"


def test_incomplete_inventory_cannot_yield_no_error():
    assert decide_reviewed((), (), policy_complete=False,
                           claim_inventory_complete=True)["status"] == "UNKNOWN"
    assert decide_reviewed((), (), policy_complete=True,
                           claim_inventory_complete=False)["status"] == "UNKNOWN"

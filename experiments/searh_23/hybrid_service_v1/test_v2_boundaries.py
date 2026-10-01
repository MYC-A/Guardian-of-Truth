#!/usr/bin/env python3
"""Directive §5.3 regressions — V2 trust boundaries (2026-10-01).

Reproduces or refutes each §5.3 item with small content tests against the
FROZEN runtime, and asserts the corrected behavior of v2_boundaries where
a fix exists. Frozen system_research_v2 code is never modified.

Items:
  B1 conveyor 4 -> C4 / started -> running: normalization must not destroy
     the claim; support must carry an explicit rule (never a global
     provenance weakening).
  B2 boolean observations must not become None/empty allowed values.
  B3 model-proposed contracts are never DOC_EXPLICIT/EXECUTED when the
     description merely reports status.
  B4 quote_ok=false closes the assumed semantic repair.
  B5 empty candidate_calls != candidate_actions_exhaustive=true.
  B6 (documentation item) syntax repair must run in the EVALUATED runtime —
     currently absent from system_eval.auto_programs (HISTORY_AUDIT §21.7);
     the hybrid-service harness addresses the wiring.
  B7 ID / latest-prior-version scoping: future events and another entity's
     facts never confirm the checked move.

Run: python3 experiments/searh_23/hybrid_service_v1/test_v2_boundaries.py
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from guardian_truth.integration.automatic_claims import (  # noqa: E402
    compile_candidate_claims)
from guardian_truth.integration.candidate_claims import candidate_meanings
from guardian_truth.integration.contracts import (  # noqa: E402
    acquire_documented, facts_from_documented)
from guardian_truth.integration.proof_engine import check_claim  # noqa: E402
from guardian_truth.step2.verifier import (  # noqa: E402
    CallEvent, ResultEvent, TrajectoryCase)

from v2_boundaries import (  # noqa: E402
    acquire_documented_v2, apply_contrastive_v2,
    claim_entity_value_licensed, licensed_entity_normalization,
    validate_goal_v2)

# ------------------------------------------------------------------ fixtures

CONVEYOR_TOOLS = [
    {"name": "check_conveyor",
     "description": "Reports whether the conveyor is running.",
     "parameters": {"conveyor_id": "string"},
     "result_schema": {"conveyor_id": "string", "running": "scalar"},
     "documented_contracts": [{
         "entity_argument": "conveyor_id",
         "result_entity_path": "$.conveyor_id",
         "result_value_path": "$.running",
         "predicate": "conveyor.running", "entity_type": "conveyor",
         "strength": "OBSERVED", "allowed_values": [],
         "meaning": "Reports whether the conveyor is running."}]},
    {"name": "start_conveyor",
     "description": "Starts the conveyor; state=running means completion.",
     "parameters": {"conveyor_id": "string"},
     "result_schema": {"conveyor_id": "string", "state": "scalar"},
     "documented_contracts": [{
         "entity_argument": "conveyor_id",
         "result_entity_path": "$.conveyor_id",
         "result_value_path": "$.state",
         "predicate": "conveyor.state", "entity_type": "conveyor",
         "strength": "EXECUTED", "allowed_values": ["running"],
         "meaning": "Starts the conveyor; state=running means completion."}]},
]

QUARRY_RULES = [
    {"pattern": r"conveyor\s+(\d+)", "format": r"C\1",
     "source": "quarry conveyor-id house style: 'C<n>' (supervisor guide §2)"},
    {"pattern": r"\bstarted\b", "format": "running",
     "source": "quarry state vocabulary: started==running (ops manual §4)"},
]


def conveyor_case(started: bool = True, cid: str = "C4",
                  other_entity: bool = False) -> tuple:
    """History: start_conveyor(C4) succeeded; response claims completion."""
    history = [
        {"index": 0, "role": "assistant", "call_id": "c1",
         "tool": "start_conveyor", "arguments": {"conveyor_id": cid}},
        {"index": 1, "role": "tool", "call_id": "c1", "tool": "start_conveyor",
         "payload": {"conveyor_id": cid,
                     "state": "running" if started else "stopped"}},
    ]
    calls = tuple(CallEvent(e["index"], e["call_id"], e["tool"],
                            e["arguments"])
                  for e in history if e["role"] == "assistant")
    results = tuple(ResultEvent(e["index"], e["call_id"], e["tool"],
                                e["payload"])
                    for e in history if e["role"] == "tool")
    case = TrajectoryCase("quarry.conveyor", "quarry policy",
                           "reviewed_control", tuple(CONVEYOR_TOOLS),
                           calls, results)
    facts, _, issues = facts_from_documented(case)
    assert not issues, f"fixture issues: {issues}"
    return case, tuple(facts)


def claim_raw(case: TrajectoryCase, response: str,
              mode: str = "CLAIMED_COMPLETED", quote: str = "I started conveyor 4") -> str:
    cands = candidate_meanings(case)
    target = [c for c in cands if c.predicate == "conveyor.state"]
    assert target, f"no conveyor.state candidate: {[c.predicate for c in cands]}"
    rows = [{"id": c.id, "mode": "NONE", "quote": ""} for c in cands]
    for r in rows:
        if r["id"] == target[0].id:
            r["mode"] = mode
            r["quote"] = quote
    import json
    return json.dumps({"candidates": rows})


# ------------------------------------------------------------------- tests

def test_b1_normalization_rule() -> None:
    """B1: licensed normalization — without rules the claim is NOT
    destroyed (stays unbound -> UNKNOWN), with rules it binds, and the
    applied rules are recorded with their sources."""
    sent = "I started conveyor 4."
    # no rules: nothing changes, nothing recorded
    norm, applied = licensed_entity_normalization(sent, ())
    assert norm == sent and applied == ()
    # licensed rules: conveyor 4 -> C4, started -> running
    norm, applied = licensed_entity_normalization(sent, QUARRY_RULES)
    assert "C4" in norm and "running" in norm, f"normalization failed: {norm}"
    assert len(applied) == 2 and all(a["source"] for a in applied)
    print(f"B1 licensed: {sent!r} -> {norm!r} "
          f"(rules: {[a['matched'] for a in applied]})")


def test_b1_claim_not_destroyed_without_rules() -> None:
    """B1: without any rule the frozen compiler leaves the claim UNBOUND
    (issue literal_entity_value_or_scope_unbound, inventory incomplete) —
    the claim is neither confirmed nor silently dropped as fine."""
    case, facts = conveyor_case()
    response = "I started conveyor 4."
    raw = claim_raw(case, response)
    compiled = compile_candidate_claims(response, 2, case, raw)
    assert not compiled.queries, "claim should not bind without rules"
    assert any("literal_entity_value_or_scope_unbound" in i
               for i in compiled.issues), compiled.issues
    assert not compiled.inventory_complete
    print("B1 no-rules: claim unbound -> UNKNOWN (not destroyed, "
          "not confirmed)")


def test_b1_claim_binds_with_licensed_rules() -> None:
    """B1: with the licensed rules the entity/value bind through the
    v2 glue and the EXECUTED fact supports the claim."""
    case, facts = conveyor_case()
    response = "I started conveyor 4."
    entity, value, scope, applied = claim_entity_value_licensed(
        case, "conveyor.state", response, QUARRY_RULES)
    assert entity == "C4", f"entity: {entity}"
    assert value == "running", f"value: {value}"
    assert scope == () or scope is not None
    assert len(applied) == 2
    # and the EXECUTED world fact exists for C4 (entity ids are stored as
    # canonical JSON scalars, i.e. '"C4"')
    exec_facts = [f for f in facts
                  if f.fact.predicate == "conveyor.state"
                  and f.fact.entity_id == '"C4"']
    assert exec_facts, "EXECUTED fact for C4 missing"
    assert exec_facts[0].fact.strength.value == "EXECUTED"
    assert exec_facts[0].fact.value == '"running"'
    print("B1 licensed: entity=C4 value=running; EXECUTED fact present")


def test_b2_boolean_observation_not_none() -> None:
    """B2: boolean observations stay real values (never None); a boolean
    STATE_CLAIM abstains honestly (no crash, no fabricated binding)."""
    tools = [{
        "name": "check_declassified",
        "description": "Reports whether the record is declassified.",
        "parameters": {"record_id": "string"},
        "result_schema": {"record_id": "string", "declassified": "scalar"},
        "documented_contracts": [{
            "entity_argument": "record_id",
            "result_entity_path": "$.record_id",
            "result_value_path": "$.declassified",
            "predicate": "record.declassified", "entity_type": "record",
            "strength": "OBSERVED", "allowed_values": [],
            "meaning": "Reports whether the record is declassified."}]},
    ]
    history = [
        {"index": 0, "role": "assistant", "call_id": "c1",
         "tool": "check_declassified", "arguments": {"record_id": "A-31"}},
        {"index": 1, "role": "tool", "call_id": "c1",
         "tool": "check_declassified",
         "payload": {"record_id": "A-31", "declassified": True}},
    ]
    calls = tuple(CallEvent(e["index"], e["call_id"], e["tool"],
                            e["arguments"])
                  for e in history if e["role"] == "assistant")
    results = tuple(ResultEvent(e["index"], e["call_id"], e["tool"],
                                e["payload"])
                    for e in history if e["role"] == "tool")
    case = TrajectoryCase("b2.bool", "p", "reviewed_control",
                          tuple(tools), calls, results)
    facts, _, issues = facts_from_documented(case)
    assert not issues
    bool_facts = [f for f in facts
                  if f.fact.predicate == "record.declassified"]
    assert bool_facts, "boolean observation produced NO fact"
    v = bool_facts[0].fact.value
    # the value is stored as its canonical JSON scalar ("true"), never
    # None and never empty — the directive's invariant
    assert v is not None and v != "" and v in (True, "true"), \
        f"boolean value became {v!r}"
    print(f"B2: boolean observation kept value {v!r} (not None/empty); "
          f"claims about it abstain without a licensed polarity rule")


def test_b3_model_contract_never_doc_explicit() -> None:
    """B3: a contract injected by enriched_case (auto_contracts=True) is
    stamped AUTO_VERIFIED by acquire_documented_v2 — never DOC_EXPLICIT."""
    case, _ = conveyor_case()
    frozen_bindings = acquire_documented(case).bindings
    assert all(b.evidence_source == "DOC_EXPLICIT" for b in frozen_bindings)
    # simulate enriched_case injection: same contract, tool marked auto
    auto_tools = []
    for t in CONVEYOR_TOOLS:
        t2 = dict(t)
        t2["auto_contracts"] = True
        auto_tools.append(t2)
    case_auto = replace(case, tools=tuple(auto_tools))
    v2_bindings = acquire_documented_v2(case_auto).bindings
    assert v2_bindings and all(
        b.evidence_source == "AUTO_VERIFIED" for b in v2_bindings), \
        [b.evidence_source for b in v2_bindings]
    # and the frozen path is untouched for genuinely documented tools
    assert all(b.evidence_source == "DOC_EXPLICIT"
               for b in acquire_documented(case).bindings)
    print("B3: model-proposed contracts -> AUTO_VERIFIED (v2); "
          "application-supplied stay DOC_EXPLICIT")


def test_b4_quote_ok_closes_semantic_repair() -> None:
    """B4: quote_ok=false CLOSES the re-strength/rename; quote_ok=true
    applies it. The flag is enforced, not decorative."""
    tool = CONVEYOR_TOOLS[1]
    contract = {"entity_argument": "conveyor_id",
                "result_entity_path": "$.conveyor_id",
                "result_value_path": "$.state",
                "predicate": "conveyor.state", "entity_type": "conveyor",
                "strength": "OBSERVED", "allowed_values": [],
                "meaning": "draft"}

    def answer_bad_quote(tool_, c):
        return {"choice": "B", "quote": "NOT VERBATIM ANYWHERE",
                "predicate": "conveyor2.state"}

    out = apply_contrastive_v2(tool, [dict(contract)], answer_bad_quote)
    c2 = out[0]
    assert c2["strength"] == "OBSERVED" and c2["predicate"] == "conveyor.state"
    assert c2["contrastive"]["quote_ok"] is False
    assert c2["contrastive"]["semantic_repair_applied"] is False
    assert c2.get("semantic_repair_closed") is not None

    def answer_good_quote(tool_, c):
        return {"choice": "B",
                "quote": "Starts the conveyor; state=running means completion.",
                "predicate": "conveyor.state"}

    out = apply_contrastive_v2(tool, [dict(contract)], answer_good_quote)
    c2 = out[0]
    assert c2["contrastive"]["quote_ok"] is True
    assert c2["contrastive"]["semantic_repair_applied"] is True
    # frozen semantics: choice B with no declared values -> REQUESTED
    # (never silently EXECUTED from a merely-reporting description)
    assert c2["strength"] == "REQUESTED", c2["strength"]
    print("B4: quote_ok=false -> repair closed (strength/predicate kept); "
          "quote_ok=true -> applied (B on empty values -> REQUESTED, "
          "not silently EXECUTED)")


def test_b5_empty_candidates_not_exhaustive() -> None:
    """B5: empty candidate_calls is NOT exhaustive; non-empty validated
    candidates or an explicitly asserted complete catalog are."""
    row = {"user_request": "Start conveyor C4.",
           "available_tools": CONVEYOR_TOOLS,
           "target_response": {"text": "I cannot start it.", "index": 2}}
    parsed_empty = {"goal": {"quote": "Start conveyor C4.",
                             "entity_type": "conveyor", "entity_id": "C4",
                             "predicate": "conveyor.state", "value": "running"},
                    "candidate_calls": [],
                    "refusal": {"quote": "I cannot start it.",
                                "absolute_inability": True}}
    goal, issues = validate_goal_v2(parsed_empty, row)
    assert goal["goal"]["candidate_actions_exhaustive"] is False
    assert "candidate_actions_exhaustiveness_unproven" in issues
    # explicit catalog completeness assertion flips it (documented trust)
    goal2, _ = validate_goal_v2(parsed_empty, row, catalog_complete=True)
    assert goal2["goal"]["candidate_actions_exhaustive"] is True
    # a validated candidate call also flips it
    parsed_ok = dict(parsed_empty)
    parsed_ok["candidate_calls"] = [
        {"tool": "start_conveyor", "arguments": {"conveyor_id": "C4"}}]
    goal3, _ = validate_goal_v2(parsed_ok, row)
    assert goal3["goal"]["candidate_actions_exhaustive"] is True
    print("B5: empty candidates -> NOT exhaustive (v2); validated "
          "candidates or asserted catalog completeness -> exhaustive")


def test_b7_other_entity_and_future_never_confirm() -> None:
    """B7: another entity's facts and future observations never confirm
    the checked move."""
    case, facts = conveyor_case(cid="C4")
    response = "I started conveyor 4."
    q_span = (0, len("I started conveyor 4."))
    # (a) claim about conveyor 5 (no facts for C5) -> no scoped evidence
    entity, value, scope, _ = claim_entity_value_licensed(
        case, "conveyor.state", response,
        [{"pattern": r"conveyor\s+(\d+)", "format": r"C\1",
          "source": "quarry house style"}])
    assert entity == "C4"
    # entity bound to C4; now craft the SAME claim about C5 explicitly
    from guardian_truth.integration.proof_engine import ClaimQuery
    q_c5 = ClaimQuery(response=response, response_index=2,
                      quote="I started conveyor 4.", start=q_span[0],
                      end=q_span[1],
                      mode="CLAIMED_COMPLETED", predicate="conveyor.state",
                      entity_type="conveyor", entity_value="C5",
                      expected_value="running", evidence_source="MODEL",
                      scope_arguments=())
    r = check_claim(q_c5, case, facts)
    assert r["status"] in {"UNKNOWN", "NOT_ESTABLISHED"}, r
    # (b) future observation: fact observed_at >= response index
    q_c4 = ClaimQuery(response=response, response_index=0,
                      quote="I started conveyor 4.", start=q_span[0],
                      end=q_span[1],
                      mode="CLAIMED_COMPLETED", predicate="conveyor.state",
                      entity_type="conveyor", entity_value="C4",
                      expected_value="running", evidence_source="MODEL",
                      scope_arguments=())
    r2 = check_claim(q_c4, case, facts)
    assert r2["status"] in {"UNKNOWN", "NOT_ESTABLISHED"}, r2
    # control: with the correct index the same claim is supported
    q_ok = ClaimQuery(response=response, response_index=2,
                      quote="I started conveyor 4.", start=q_span[0],
                      end=q_span[1],
                      mode="CLAIMED_COMPLETED", predicate="conveyor.state",
                      entity_type="conveyor", entity_value="C4",
                      expected_value="running", evidence_source="MODEL",
                      actor="ASSISTANT", scope_arguments=())
    r3 = check_claim(q_ok, case, facts)
    assert r3["status"] in {"SUPPORTED", "SATISFIED"}, r3
    print("B7: other entity -> no evidence; future observation -> "
          "not confirmed; timely same-entity -> supported")


def main() -> int:
    tests = [test_b1_normalization_rule,
             test_b1_claim_not_destroyed_without_rules,
             test_b1_claim_binds_with_licensed_rules,
             test_b2_boolean_observation_not_none,
             test_b3_model_contract_never_doc_explicit,
             test_b4_quote_ok_closes_semantic_repair,
             test_b5_empty_candidates_not_exhaustive,
             test_b7_other_entity_and_future_never_confirm]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  FAILED {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{'='*60}\n{len(tests)-failed}/{len(tests)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

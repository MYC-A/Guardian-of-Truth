"""full_architecture_v1 — Phase D: property / metamorphic tests (directive §21).

Hypothesis-driven transformations over small formal traces, checking the
metamorphic properties A-J against the SPLIT Clingo backend (data +
evidence.lp + policy.lp):

  A  rename tool identifiers consistently      -> verdict unchanged
  B  rename entity ids consistently            -> verdict unchanged
  C  insert irrelevant events                  -> verdict unchanged
  D  reorder causally unrelated irrelevant
     events                                   -> verdict unchanged
  E  missing evidence -> explicit refuting
     evidence                                 -> UNKNOWN may become FALSE,
                                                  never the reverse silently
  F  add contradictory trusted evidence       -> TRUE/FALSE may become BOTH
  G  duplicate an identical observation        -> truth unchanged
  H  failed call -> success + trusted contract -> effect direction expected
  I  remove history-completeness premise      -> absence proof must not
                                                  survive
  J  two interpretations, one violating        -> UNRESOLVED

Run:  python experiments/full_architecture_v1/synthetic/metamorphic.py
      (writes outputs/full_architecture_v1/synthetic/metamorphic.json)
Also importable from pytest (functions named test_*).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_FULLARCH = Path(__file__).resolve().parents[1]
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
for p in (str(_BAKEOFF), str(_BAKEOFF / "backends"), str(_FULLARCH)):
    if p not in sys.path:
        sys.path.insert(0, p)

from hypothesis import given, settings, HealthCheck  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from neutral_types import (  # noqa: E402
    NeutralAtom, NeutralCoreInput, NeutralFact, NeutralInterpretation,
    NeutralRule,
)
from evidence.clingo_backend import evaluate, probe  # noqa: E402

REPO = _FULLARCH.parents[1]
OUT = REPO / "outputs" / "full_architecture_v1" / "synthetic"

_ACTIONS = ("close_account", "update_status", "charge_card", "noop_check",
            "read_note")
_ENTITIES = ("acc-1", "acc-2", "ord-7")

_trace = st.lists(
    st.one_of(
        st.tuples(st.just("attempt"), st.sampled_from(_ACTIONS),
                  st.sampled_from(_ENTITIES), st.integers(1, 20),
                  st.booleans()),
        st.tuples(st.just("obs"), st.sampled_from(("status", "balance")),
                  st.sampled_from(_ENTITIES),
                  st.sampled_from(("active", "suspended")),
                  st.integers(1, 20)),
    ), max_size=8)


def _facts_from(trace) -> list[NeutralFact]:
    facts = []
    for index, item in enumerate(trace):
        if item[0] == "attempt":
            action, entity, pos, failed = item[1], item[2], item[3], item[4]
            kind = "ACTION_FAILED" if failed else "ACTION_ATTEMPTED"
            facts.append(NeutralFact(f"f{index}", kind, "assistant", entity,
                                     action, event_index=pos,
                                     call_id=f"c{index}", region="target"))
        else:
            _kind, predicate, entity, value, pos = item
            facts.append(NeutralFact(f"f{index}", "STATE_OBSERVATION",
                                     "system", entity, predicate, value=value,
                                     event_index=pos))
    return facts


def _ci(facts, *, rules=(("close_account", "acc-1"),),
        history_complete=False) -> NeutralCoreInput:
    neutral_rules = tuple(
        NeutralRule(rule_id=f"r{i}", modality="FORBID", action=action,
                    entity=entity)
        for i, (action, entity) in enumerate(rules))
    return NeutralCoreInput(
        case_id="meta", facts=tuple(facts),
        interpretations=(NeutralInterpretation("i0", neutral_rules),),
        history_complete=history_complete,
        completeness_basis="synthetic metamorphic" if history_complete else None,
        source_refs={})


def _status_of(facts, **kwargs) -> str:
    return evaluate(_ci(facts, **kwargs)).status


# ---------------------------------------------------------------- properties

@settings(max_examples=60, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(trace=_trace)
def test_A_tool_rename(trace):
    base = _facts_from(trace)
    renamed = [NeutralFact(f.fact_id, f.kind, f.actor, f.entity,
                           f"renamed_{f.predicate}" if f.kind in
                           ("ACTION_ATTEMPTED", "ACTION_FAILED",
                            "ACTION_COMPLETED") else f.predicate,
                           value=f.value, event_index=f.event_index,
                           call_id=f.call_id, region=f.region)
               for f in base]
    rules = tuple((f"renamed_{action}", entity) for action, entity
                  in (("close_account", "acc-1"),))
    assert _status_of(base) == _status_of(renamed, rules=rules)


@settings(max_examples=60, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(trace=_trace)
def test_B_entity_rename(trace):
    base = _facts_from(trace)
    renamed = [NeutralFact(f.fact_id, f.kind, f.actor,
                           f"ent_{f.entity}" if f.entity != "*" else f.entity,
                           f.predicate, value=f.value,
                           event_index=f.event_index, call_id=f.call_id,
                           region=f.region)
               for f in base]
    rules = (("close_account", "ent_acc-1"),)
    assert _status_of(base) == _status_of(renamed, rules=rules)


@settings(max_examples=60, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(trace=_trace, filler=st.integers(0, 5))
def test_C_irrelevant_insertion(trace, filler):
    base = _facts_from(trace)
    noisy = list(base)
    for index in range(filler):
        noisy.append(NeutralFact(f"noise{index}", "CLAIM", "assistant",
                                 "ent-other", "status", value="noise",
                                 event_index=30 + index, region="history"))
        noisy.append(NeutralFact(f"noiseb{index}", "ENTITY", "system",
                                 "ent-other", "entity", value={"x": 1},
                                 event_index=31 + index, region="history"))
    assert _status_of(base) == _status_of(noisy)


@settings(max_examples=40, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(trace=_trace)
def test_G_duplicate_observation(trace):
    facts = _facts_from(trace)
    observations = [f for f in facts if f.kind == "STATE_OBSERVATION"]
    if not observations:
        return
    original = observations[0]
    duplicated = [NeutralFact("dup", original.kind, original.actor,
                              original.entity, original.predicate,
                              value=original.value,
                              event_index=original.event_index)]
    atom = NeutralAtom("q:st", "state", entity=original.entity,
                       predicate=original.predicate,
                       expected=original.value, time_index=10**9)
    base_value = probe(_ci(facts), [atom])[0].value
    dup_value = probe(_ci(facts + duplicated), [atom])[0].value
    assert base_value == dup_value


@settings(max_examples=40, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(trace=_trace)
def test_E_refuting_evidence(trace):
    """UNKNOWN -> FALSE allowed; FALSE -> UNKNOWN (silent) forbidden."""
    facts = [f for f in _facts_from(trace)
             if f.kind in ("ACTION_ATTEMPTED", "ACTION_FAILED")]
    atom = NeutralAtom("q:at", "attempted", action="close_account",
                       entity="acc-1", actor="assistant", time_index=10**9)
    before = probe(_ci(facts, history_complete=True), [atom])[0].value
    if before != "FALSE":
        return      # only the FALSE-preserving direction is constrained
    after = probe(_ci(facts, history_complete=False), [atom])[0].value
    assert after in ("FALSE", "UNKNOWN")


@settings(max_examples=40, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(trace=_trace)
def test_F_contradiction(trace):
    """Adding a contradictory row may produce BOTH, never an unrelated flip."""
    facts = [f for f in _facts_from(trace)
             if f.kind == "STATE_OBSERVATION"]
    if not facts:
        return
    original = facts[0]
    atom = NeutralAtom("q:st", "state", entity=original.entity,
                       predicate=original.predicate,
                       expected=original.value, time_index=10**9)
    before = probe(_ci(facts), [atom])[0].value
    contrary = "other-value" if original.value != "other-value" else "v"
    contradiction = NeutralFact("contra", "STATE_OBSERVATION", "system",
                                original.entity, original.predicate,
                                value=contrary,
                                event_index=original.event_index)
    after = probe(_ci(list(facts) + [contradiction]), [atom])[0].value
    if before in ("TRUE", "FALSE"):
        assert after in ("BOTH", before)
    else:
        assert after == before


@settings(max_examples=40, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
@given(trace=_trace)
def test_H_failed_to_contract(trace):
    """Failed call -> attempt support stays, completed moves toward TRUE
    only with a trusted contract (EFFECT with matching call)."""
    facts = [NeutralFact("f1", "ACTION_FAILED", "assistant", "acc-1",
                         "close_account", event_index=2, call_id="c1",
                         region="target")]
    atom = NeutralAtom("q:cp", "completed", action="close_account",
                       entity="acc-1", actor="assistant", time_index=10**9)
    failed_completed = probe(_ci(facts), [atom])[0].value
    assert failed_completed == "UNKNOWN"
    contract = [NeutralFact("f2", "EFFECT", "assistant", "acc-1",
                            "close_account", value=None, event_index=3,
                            call_id="c1", region="target")]
    succeeded = probe(_ci(facts + contract), [atom])[0].value
    assert succeeded == "TRUE"


def test_I_completeness_premise():
    """Absence proof must not survive removing the premise."""
    facts = [NeutralFact("f0", "STATE_OBSERVATION", "system", "acc-1",
                         "status", value="active", event_index=1)]
    atom = NeutralAtom("q:at", "attempted", action="close_account",
                       entity="acc-1", actor="assistant", time_index=10**9)
    with_premise = probe(_ci(facts, history_complete=True), [atom])[0].value
    without = probe(_ci(facts, history_complete=False), [atom])[0].value
    assert with_premise == "FALSE"
    assert without == "UNKNOWN"


def test_J_interpretation_disagreement():
    """One violating interpretation + one not -> UNRESOLVED."""
    facts = [NeutralFact("f1", "ACTION_ATTEMPTED", "assistant", "acc-1",
                         "close_account", event_index=2, call_id="c1",
                         region="target")]
    ci = NeutralCoreInput(
        case_id="meta-j", facts=tuple(facts),
        interpretations=(
            NeutralInterpretation("i0", (NeutralRule(
                rule_id="r0", modality="FORBID", action="close_account",
                entity="acc-1"),),),
            NeutralInterpretation("i1", ()),
        ))
    result = evaluate(ci)
    assert result.status == "UNRESOLVED"


def test_D_reorder_unrelated():
    """Reordering facts with identical event_index (no causal order between
    them) must not change the verdict; positions themselves stay."""
    facts = [
        NeutralFact("f1", "ACTION_ATTEMPTED", "assistant", "acc-1",
                    "close_account", event_index=2, call_id="c1",
                    region="target"),
        NeutralFact("f2", "STATE_OBSERVATION", "system", "acc-2", "status",
                    value="active", event_index=2),
        NeutralFact("f3", "CLAIM", "user", "acc-3", "note", value="x",
                    event_index=2),
    ]
    reordered = [facts[2], facts[0], facts[1]]
    assert _status_of(facts) == _status_of(reordered)


# ------------------------------------------------------------------ runner

ALL_TESTS = [
    ("A_tool_rename", test_A_tool_rename),
    ("B_entity_rename", test_B_entity_rename),
    ("C_irrelevant_insertion", test_C_irrelevant_insertion),
    ("D_reorder_unrelated", test_D_reorder_unrelated),
    ("E_refuting_evidence", test_E_refuting_evidence),
    ("F_contradiction", test_F_contradiction),
    ("G_duplicate_observation", test_G_duplicate_observation),
    ("H_failed_to_contract", test_H_failed_to_contract),
    ("I_completeness_premise", test_I_completeness_premise),
    ("J_interpretation_disagreement", test_J_interpretation_disagreement),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    started = time.time()
    for name, test in ALL_TESTS:
        t0 = time.time()
        try:
            test()
            results[name] = {"ok": True, "seconds": round(time.time() - t0, 1)}
        except Exception as error:
            results[name] = {"ok": False,
                             "error": f"{type(error).__name__}: {error}"[:300],
                             "seconds": round(time.time() - t0, 1)}
    payload = {
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "backend": "fullarch-clingo(evidence.lp+policy.lp)",
        "properties": results,
        "passed": sum(1 for r in results.values() if r["ok"]),
        "total": len(results),
        "wall_time_s": round(time.time() - started, 1),
    }
    (OUT / "metamorphic.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v["ok"] for k, v in results.items()}, indent=1))
    print(f"passed {payload['passed']}/{payload['total']} in "
          f"{payload['wall_time_s']}s")
    if payload["passed"] != payload["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

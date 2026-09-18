"""core_engine_bakeoff_v1 — controlled performance scaling.

Two axes (per the directive):
  * EVENTS: 100 / 1,000 / 10,000 irrelevant facts around one audited
    violation (the s28/s29 noise shape), one interpretation, one rule.
  * RULES: 1 / 10 / 50 / 100 rules in ONE interpretation over a fixed
    200-fact trace (rules that mostly do not fire; a handful target the
    audited attempt).

Measures wall-clock per backend (evaluate only, process startup included
for the subprocess backends — the honest end-to-end number on THIS 2-core
machine).  Absolute numbers are NOT production performance; the comparison
is about RELATIVE behavior and failure modes.
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = REPO / "outputs" / "core_engine_bakeoff_v1"
sys.path.insert(0, str(HERE))

from neutral_types import (CondNode, NeutralAtom, NeutralCardinality,
                           NeutralComparison, NeutralCoreInput, NeutralFact,
                           NeutralInterpretation, NeutralRule)

from scenarios import attempt as mk_attempt, obs as mk_obs, claim as mk_claim

BACKENDS = ("current_guardian", "clingo_backend", "scasp_backend",
            "drools_backend")


def _noise_facts(n: int, rng: random.Random) -> list[NeutralFact]:
    facts: list[NeutralFact] = []
    tools = ("list_items", "noop_check", "ping_status", "read_note",
             "touch_record")
    for i in range(n):
        idx = i + 1
        kind = i % 4
        entity = f"e-{rng.randrange(100000)}"
        if kind == 0:
            facts.append(mk_attempt(f"n{i}", rng.choice(tools), idx, entity,
                                    region="history", call_id=f"nc-{i}"))
        elif kind == 1:
            facts.append(mk_claim(f"n{i}", "status", "fine", idx, entity))
        elif kind == 2:
            facts.append(mk_obs(f"n{i}", "ping", "ok", idx, entity))
        else:
            facts.append(NeutralFact(f"n{i}", "ENTITY", "system", entity,
                                     "entity", value={"id": entity},
                                     event_index=idx, region="history"))
    return facts


def event_scaling_input(n: int) -> NeutralCoreInput:
    rng = random.Random(20260918)
    facts = _noise_facts(n, rng)
    target_idx = n + 3
    facts.append(mk_attempt("t1", "close_account", target_idx, "acc-1",
                            call_id="call-target"))
    return NeutralCoreInput(
        case_id=f"perf-events-{n}", facts=tuple(facts),
        interpretations=(NeutralInterpretation(
            "i1", (NeutralRule("r0", "FORBID", "close_account",
                               entity="acc-1"),)),),
        history_complete=True,
        completeness_basis="controlled synthetic history",
        closed_action_universe=("close_account",),
        source_refs={})


def rule_scaling_input(n_rules: int) -> NeutralCoreInput:
    rng = random.Random(20260919)
    facts = _noise_facts(200, rng)
    facts.append(mk_attempt("t1", "close_account", 250, "acc-1",
                            call_id="call-target"))
    facts.append(mk_obs("s1", "balance", 50, 240, "acc-1"))
    rules: list[NeutralRule] = []
    # rule 0: the one that fires (a comparison-gated prohibition — the
    # expressivity the external engines have and the incumbent lacks)
    rules.append(NeutralRule(
        "r0", "FORBID", "close_account", entity="acc-1",
        conditions=CondNode(atom=NeutralAtom(
            "c0", "comparison", entity="acc-1", predicate="balance",
            comparison=NeutralComparison("balance", "LT", 100),
            time_index=-1))))
    for i in range(1, n_rules):
        # non-firing rules: forbidden actions that never happen, with a mix
        # of attempt conditions and cardinality exceptions
        action = f"never_action_{i}"
        if i % 3 == 0:
            cond = CondNode(atom=NeutralAtom(
                f"c{i}", "attempted", action=f"never_prereq_{i}",
                entity="acc-1", time_index=-1))
            rules.append(NeutralRule(f"r{i}", "FORBID", action,
                                     entity="acc-1", conditions=cond))
        elif i % 3 == 1:
            rules.append(NeutralRule(f"r{i}", "REQUIRE", action,
                                     entity="acc-9"))
        else:
            exc = CondNode(atom=NeutralAtom(
                f"e{i}", "cardinality", action=f"never_ver_{i}",
                entity="acc-1",
                cardinality=NeutralCardinality(f"never_ver_{i}", "AT_LEAST", 2),
                time_index=-1))
            rules.append(NeutralRule(f"r{i}", "FORBID", action,
                                     entity="acc-1", exceptions=(exc,)))
    return NeutralCoreInput(
        case_id=f"perf-rules-{n_rules}", facts=tuple(facts),
        interpretations=(NeutralInterpretation("i1", tuple(rules)),),
        history_complete=True,
        completeness_basis="controlled synthetic history",
        closed_action_universe=("close_account",),
        source_refs={})


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    for backend_name in BACKENDS:
        import importlib
        try:
            module = importlib.import_module(f"backends.{backend_name}")
        except Exception as error:
            results[backend_name] = {"error": f"import: {error}"}
            continue
        rows = {}
        for n in (100, 1000, 10000):
            ci = event_scaling_input(n)
            t0 = time.perf_counter()
            try:
                result = module.evaluate(ci)
                elapsed = round(time.perf_counter() - t0, 2)
                rows[f"events_{n}"] = {
                    "runtime_s": elapsed, "status": result.status,
                    "models_or_notes": result.notes[:80]}
            except Exception as error:
                rows[f"events_{n}"] = {"error":
                                       f"{type(error).__name__}: {str(error)[:120]}"}
            print(backend_name, f"events_{n}", rows[f"events_{n}"],
                  flush=True)
        for n in (1, 10, 50, 100):
            ci = rule_scaling_input(n)
            t0 = time.perf_counter()
            try:
                result = module.evaluate(ci)
                elapsed = round(time.perf_counter() - t0, 2)
                rows[f"rules_{n}"] = {
                    "runtime_s": elapsed, "status": result.status,
                    "models_or_notes": result.notes[:80]}
            except Exception as error:
                rows[f"rules_{n}"] = {"error":
                                      f"{type(error).__name__}: {str(error)[:120]}"}
            print(backend_name, f"rules_{n}", rows[f"rules_{n}"],
                  flush=True)
        results[backend_name] = rows
    payload = {
        "note": "2-core CPU, 3.9GiB RAM sandbox; wall-clock includes process "
                "startup for subprocess backends (scasp: one process PER "
                "query; drools: one JVM per case). Relative behavior only.",
        "backends": results,
    }
    (OUT / "performance.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written performance.json")


if __name__ == "__main__":
    main()

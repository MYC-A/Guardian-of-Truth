"""Freeze the mini validation set (10 new cases) BEFORE running H2 or any
post-hoc arm on it. Emits frozen_mini/ + SHAs. Same conventions as main."""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from oc_cases_mini import CASES_MINI
from oc_freeze import (validate as _validate_unused, runner_case, gold_case,
                       make_rename_map as _mr_unused)

ROLES = {"OPERATION_EFFECT", "PRECONDITION_CHECK", "STATE_OBSERVATION",
         "COMMUNICATION", "OTHER"}
RELATIONS = {"GATE", "ORDER_BEFORE", "ORDER_AFTER", "EXCEPTION", "EVEN_IF"}
NEED_TOOLS = ROLES - {"OTHER"}
SEED = 20261001


def fail(msg):
    print(f"MINI_FREEZE_ERROR: {msg}")
    sys.exit(1)


def apply_entity_renames(text, entity_map):
    for code in sorted(entity_map, key=len, reverse=True):
        text = text.replace(code, entity_map[code])
    return text


def validate():
    for case in CASES_MINI:
        policy = case["policy"]
        tool_names = [t["name"] for t in case["tools"]]
        event_spans = []
        for span, role, tools in case["gold_events"]:
            if span not in policy:
                fail(f"{case['id']}: span not substring: {span!r}")
            if role not in ROLES:
                fail(f"{case['id']}: bad role")
            if role in NEED_TOOLS and not tools:
                fail(f"{case['id']}: {span!r} needs tool")
            if role == "OTHER" and tools:
                fail(f"{case['id']}: OTHER with tools")
            for t in tools:
                if t not in tool_names:
                    fail(f"{case['id']}: unknown tool {t}")
            event_spans.append(span)
        for edge in case["gold_edges"]:
            cond, op, rel = edge[0], edge[1], edge[2]
            ref = edge[3] if len(edge) > 3 else None
            if cond not in policy:
                fail(f"{case['id']}: edge cond not substring: {cond!r}")
            if op not in policy:
                fail(f"{case['id']}: edge op not substring: {op!r}")
            if rel not in RELATIONS:
                fail(f"{case['id']}: bad relation {rel}")
            if ref is not None and ref not in event_spans:
                fail(f"{case['id']}: ref not event: {ref!r}")
            if op not in event_spans and ref is None:
                fail(f"{case['id']}: edge op not event and no ref: {op!r}")
            if cond not in event_spans and ref is None:
                fail(f"{case['id']}: edge cond not event and no ref: {cond!r}")
        for code in case["entity_codes"]:
            if code not in policy:
                fail(f"{case['id']}: entity {code} not in policy")
    ids = [c["id"] for c in CASES_MINI]
    if len(set(ids)) != len(ids):
        fail("duplicate ids")
    print(f"mini validation OK: {len(CASES_MINI)} cases, "
          f"{sum(len(c['gold_events']) for c in CASES_MINI)} events, "
          f"{sum(len(c['gold_edges']) for c in CASES_MINI)} edges")


def main():
    validate()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "frozen_mini"
    out.mkdir(parents=True, exist_ok=True)

    rng = random.Random(SEED)
    letters = "abcdefghijklmnopqrstuvwxyz"
    tool_map, entity_map, used = {}, {}, set()

    def new_tool():
        while True:
            n = f"tool_{rng.choice(letters)}{rng.randint(10, 99)}"
            if n not in used:
                used.add(n)
                return n

    def new_entity():
        while True:
            c = f"{rng.choice(letters)}{rng.choice(letters)}-{rng.randint(10, 99)}"
            if c not in used:
                used.add(c)
                return c

    for case in CASES_MINI:
        for t in case["tools"]:
            tool_map[t["name"]] = new_tool()
        for code in case["entity_codes"]:
            entity_map[code] = new_entity()

    runner = [runner_case(c) for c in CASES_MINI]
    gold = [gold_case(c) for c in CASES_MINI]
    comp = [{"case_id": c["id"], "spans": [e[0] for e in c["gold_events"]]}
            for c in CASES_MINI]

    renamed_runner, renamed_gold, renamed_comp = [], [], []
    for case in CASES_MINI:
        policy = apply_entity_renames(case["policy"], entity_map)
        tools = [{"name": tool_map[t["name"]],
                  "description": apply_entity_renames(t["description"], entity_map),
                  "input": t["input"], "output": t["output"]} for t in case["tools"]]
        events = []
        for span, role, gv in case["gold_events"]:
            rspan = apply_entity_renames(span, entity_map)
            if rspan not in policy:
                fail(f"{case['id']}: renamed span not found: {rspan!r}")
            events.append({"source_span": rspan, "role": role,
                           "governed_tools": [tool_map[g] for g in gv]})
        edges = []
        for e in case["gold_edges"]:
            rcond = apply_entity_renames(e[0], entity_map)
            rop = apply_entity_renames(e[1], entity_map)
            edge = {"condition_span": rcond, "operation_span": rop, "relation": e[2]}
            if len(e) > 3:
                edge["ref_span"] = apply_entity_renames(e[3], entity_map)
            edges.append(edge)
        renamed_runner.append({"case_id": case["id"], "domain": case["domain"],
                                "policy": policy, "tools": tools})
        renamed_gold.append({"case_id": case["id"], "candidate_events": events,
                             "condition_edges": edges,
                             "tool_types": {tool_map[t["name"]]: t["type"]
                                            for t in case["tools"]}})
        renamed_comp.append({"case_id": case["id"],
                             "spans": [ev["source_span"] for ev in events]})

    artifacts = {
        "frozen_cases_mini.json": runner,
        "gold_mini.json": gold,
        "component_inputs_mini.json": comp,
        "frozen_cases_mini_renamed.json": renamed_runner,
        "gold_mini_renamed.json": renamed_gold,
        "rename_map_mini.json": {"tools": tool_map, "entities": entity_map, "seed": SEED},
    }
    for name, payload in artifacts.items():
        p = out / name
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{name} sha256={hashlib.sha256(p.read_bytes()).hexdigest()}")
    roles = {}
    for g in gold:
        for ev in g["candidate_events"]:
            roles[ev["role"]] = roles.get(ev["role"], 0) + 1
    print("role counts:", json.dumps(roles, sort_keys=True))


if __name__ == "__main__":
    main()

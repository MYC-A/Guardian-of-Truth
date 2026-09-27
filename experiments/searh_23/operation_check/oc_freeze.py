"""Freeze the operation-check dataset: validate, emit runner cases + gold +
renamed suite, print SHA256 digests. Pure stdlib; runs locally and on server.

Outputs (written next to this script's OUT dir):
  frozen_cases.json        runner input, original suite (no gold, no tool types)
  gold.json                gold for the original suite (scorer only)
  frozen_cases_renamed.json  runner input, renamed suite
  gold_renamed.json          gold for the renamed suite
  rename_map.json            tool-name and entity-code mapping (scorer only)
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from oc_cases import CASES_A
from oc_cases_b import CASES_B

ROLES = {"OPERATION_EFFECT", "PRECONDITION_CHECK", "STATE_OBSERVATION",
         "COMMUNICATION", "OTHER"}
RELATIONS = {"GATE", "ORDER_BEFORE", "ORDER_AFTER", "EXCEPTION", "EVEN_IF"}
NEED_TOOLS = ROLES - {"OTHER"}

REQUIRED_CONSTRUCTIONS = [
    "check-before", "only-if", "after-x-perform-y", "requires-and", "requires-or",
    "observe-then", "confirmation-before", "a-before-b", "may-but-forbidden",
    "unless-not", "even-if-never", "multiple-operations", "multiple-checks-one-op",
    "shared-check-multi-ops", "descriptive-noop", "communication-obligation",
]

CASES = CASES_A + CASES_B
SEED = 20260927


def fail(msg):
    print(f"FREEZE_VALIDATION_ERROR: {msg}")
    sys.exit(1)


def validate():
    seen_constructions = set()
    for case in CASES:
        policy = case["policy"]
        tool_names = [t["name"] for t in case["tools"]]
        if len(set(tool_names)) != len(tool_names):
            fail(f"{case['id']}: duplicate tool names")
        event_spans = []
        for span, role, tools in case["gold_events"]:
            if span not in policy:
                fail(f"{case['id']}: event span not a substring: {span!r}")
            if role not in ROLES:
                fail(f"{case['id']}: bad role {role}")
            if role in NEED_TOOLS and not tools:
                fail(f"{case['id']}: event {span!r} needs a governed tool")
            if role == "OTHER" and tools:
                fail(f"{case['id']}: OTHER event {span!r} must have no tools")
            for t in tools:
                if t not in tool_names:
                    fail(f"{case['id']}: unknown tool {t} for event {span!r}")
            event_spans.append(span)
        for edge in case["gold_edges"]:
            cond, op, rel = edge[0], edge[1], edge[2]
            ref = edge[3] if len(edge) > 3 else None
            if cond not in policy:
                fail(f"{case['id']}: edge condition span not a substring: {cond!r}")
            if op not in policy:
                fail(f"{case['id']}: edge operation span not a substring: {op!r}")
            if rel not in RELATIONS:
                fail(f"{case['id']}: bad relation {rel}")
            if ref is not None and ref not in event_spans:
                fail(f"{case['id']}: edge ref span is not a gold event: {ref!r}")
            # the operation endpoint must be a gold event span or carry a ref
            if op not in event_spans and ref is None:
                fail(f"{case['id']}: edge operation span is not a gold event and has no ref: {op!r}")
            if cond not in event_spans and ref is None:
                fail(f"{case['id']}: edge condition span is not a gold event and has no ref: {cond!r}")
        for code in case["entity_codes"]:
            if code not in policy:
                fail(f"{case['id']}: entity code {code} not in policy")
        seen_constructions.update(case["constructions"])
    missing = [c for c in REQUIRED_CONSTRUCTIONS if c not in seen_constructions]
    if missing:
        fail(f"construction coverage missing: {missing}")
    ids = [c["id"] for c in CASES]
    if len(set(ids)) != len(ids):
        fail("duplicate case ids")
    print(f"validation OK: {len(CASES)} cases, "
          f"{sum(len(c['gold_events']) for c in CASES)} gold events, "
          f"{sum(len(c['gold_edges']) for c in CASES)} gold edges")


def runner_case(case):
    return {
        "case_id": case["id"],
        "domain": case["domain"],
        "policy": case["policy"],
        "tools": [
            {"name": t["name"], "description": t["description"],
             "input": t["input"], "output": t["output"]}
            for t in case["tools"]
        ],
    }


def gold_case(case):
    events = [
        {"source_span": s, "role": r, "governed_tools": list(t)}
        for s, r, t in case["gold_events"]
    ]
    edges = []
    for e in case["gold_edges"]:
        edge = {"condition_span": e[0], "operation_span": e[1], "relation": e[2]}
        if len(e) > 3:
            edge["ref_span"] = e[3]
        edges.append(edge)
    return {
        "case_id": case["id"],
        "candidate_events": events,
        "condition_edges": edges,
        "tool_types": {t["name"]: t["type"] for t in case["tools"]},
    }


def make_rename_map():
    rng = random.Random(SEED)
    letters = "abcdefghijklmnopqrstuvwxyz"
    tool_map = {}
    entity_map = {}
    used = set()

    def new_tool_name():
        while True:
            name = f"tool_{rng.choice(letters)}{rng.randint(10, 99)}"
            if name not in used:
                used.add(name)
                return name

    def new_entity_code():
        while True:
            code = f"{rng.choice(letters)}{rng.choice(letters)}-{rng.randint(10, 99)}"
            if code not in used:
                used.add(code)
                return code

    for case in CASES:
        for t in case["tools"]:
            tool_map[t["name"]] = new_tool_name()
        for code in case["entity_codes"]:
            entity_map[code] = new_entity_code()
    return tool_map, entity_map


def apply_entity_renames(text, entity_map):
    # longest codes first to avoid partial-prefix collisions
    for code in sorted(entity_map, key=len, reverse=True):
        text = text.replace(code, entity_map[code])
    return text


def renamed_case(case, tool_map, entity_map):
    policy = apply_entity_renames(case["policy"], entity_map)
    tools = []
    for t in case["tools"]:
        tools.append({
            "name": tool_map[t["name"]],
            "description": apply_entity_renames(t["description"], entity_map),
            "input": t["input"],
            "output": t["output"],
        })
    # event spans: rename entity codes inside them, verify unique re-location
    events = []
    for span, role, gv in case["gold_events"]:
        rspan = apply_entity_renames(span, entity_map)
        if rspan not in policy:
            fail(f"{case['id']}: renamed event span not found: {rspan!r}")
        events.append({
            "source_span": rspan,
            "role": role,
            "governed_tools": [tool_map[g] for g in gv],
        })
    edges = []
    for e in case["gold_edges"]:
        rcond = apply_entity_renames(e[0], entity_map)
        rop = apply_entity_renames(e[1], entity_map)
        for s in (rcond, rop):
            if s not in policy:
                fail(f"{case['id']}: renamed edge span not found: {s!r}")
        edge = {"condition_span": rcond, "operation_span": rop, "relation": e[2]}
        if len(e) > 3:
            rref = apply_entity_renames(e[3], entity_map)
            if rref not in policy:
                fail(f"{case['id']}: renamed ref span not found: {rref!r}")
            edge["ref_span"] = rref
        edges.append(edge)
    return {
        "runner": {"case_id": case["id"], "domain": case["domain"],
                   "policy": policy, "tools": tools},
        "gold": {"case_id": case["id"], "candidate_events": events,
                 "condition_edges": edges,
                 "tool_types": {tool_map[t["name"]]: t["type"] for t in case["tools"]}},
    }


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    validate()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "frozen"
    out.mkdir(parents=True, exist_ok=True)

    tool_map, entity_map = make_rename_map()

    original_runner = [runner_case(c) for c in CASES]
    original_gold = [gold_case(c) for c in CASES]

    renamed_runner = []
    renamed_gold = []
    for case in CASES:
        pair = renamed_case(case, tool_map, entity_map)
        renamed_runner.append(pair["runner"])
        renamed_gold.append(pair["gold"])

    # spans-only component inputs (derived from gold, contain NO labels/tools)
    comp_inputs = [{"case_id": c["id"], "spans": [e[0] for e in c["gold_events"]]}
                   for c in CASES]
    comp_inputs_renamed = []
    for case in CASES:
        renamed = renamed_case(case, tool_map, entity_map)
        comp_inputs_renamed.append({
            "case_id": case["id"],
            "spans": [ev["source_span"] for ev in renamed["gold"]["candidate_events"]],
        })

    artifacts = {
        "frozen_cases.json": original_runner,
        "gold.json": original_gold,
        "frozen_cases_renamed.json": renamed_runner,
        "gold_renamed.json": renamed_gold,
        "component_inputs.json": comp_inputs,
        "component_inputs_renamed.json": comp_inputs_renamed,
        "rename_map.json": {"tools": tool_map, "entities": entity_map, "seed": SEED},
    }
    for name, payload in artifacts.items():
        path = out / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        print(f"{name} sha256={sha256(path)}")

    roles = {}
    for g in original_gold:
        for ev in g["candidate_events"]:
            roles[ev["role"]] = roles.get(ev["role"], 0) + 1
    rels = {}
    for g in original_gold:
        for ed in g["condition_edges"]:
            rels[ed["relation"]] = rels.get(ed["relation"], 0) + 1
    print("role counts:", json.dumps(roles, sort_keys=True))
    print("relation counts:", json.dumps(rels, sort_keys=True))


if __name__ == "__main__":
    main()

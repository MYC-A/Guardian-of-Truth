"""Freeze the RELATION_GRAPH_v1 dataset: validate, emit runner cases + gold +
relation inputs + renamed suites + SHA256 manifest. Pure stdlib.

Run:  python3 rel_freeze.py [outdir]

Conventions fixed BEFORE any inference (see rel_cases_main.py docstring).
The freeze also computes the candidate pair universe (from-side = every
non-OTHER event, to-side = OPERATION_EFFECT or COMMUNICATION events) so that
relation-detection precision can be measured against a fixed pair space.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rel_cases_main import CASES_MAIN
from rel_cases_mini import CASES_MINI

ROLES = {"OPERATION_EFFECT", "PRECONDITION_CHECK", "STATE_OBSERVATION",
         "COMMUNICATION", "OTHER"}
RELATIONS = {"PRECONDITION", "STATE_GATE", "ORDER_BEFORE", "ORDER_AFTER",
             "RESPONSE", "EXCEPTION", "EVEN_IF"}
GOLD_RELATIONS = RELATIONS - {"ORDER_AFTER"}  # stored canonically earlier->later
TOOL_TYPES = {"mutate", "verify", "read", "communicate"}

REQUIRED_CONSTRUCTIONS = [
    # §7 configuration coverage
    "check-before",            # one condition -> one operation
    "requires-and",            # several conditions -> one operation (AND)
    "requires-or",             # OR
    "shared-check-multi-ops",  # one condition -> several operations
    "adjacent-op-trap",        # several operations nearby (wrong-binding trap)
    "nested-conditions",       # nested conditions (cond-on-cond chain)
    "op-before-op",            # temporal relation without prerequisite
    "mixed-order",             # CHECK->OP vs OP->OP discrimination
    "unless-not",              # exception / unless
    "even-if",                 # even if (non-blocking)
    "descriptive-noop",        # descriptive event without relation
    "comm-adjacent",           # communication event near business operation
    "unrelated-events",        # unrelated events in one policy (false edges)
    # minimal-pair mechanisms
    "direction-flip",          # MP2 A-before-B vs B-before-A
    "same-phrase-trap",        # MP4 condition vs same phrase as description
    "split-clause",            # MP6 same events, different clause structure
    "standalone-check-noedge", # MP1b check with no gated operation
    "distance-trap",           # condition binds across an intervening sentence
    "misleading-tool-name",    # tool name contradicts description
]

SEED = 20260928


def fail(msg):
    print(f"FREEZE_VALIDATION_ERROR: {msg}")
    sys.exit(1)


def validate(cases, label):
    seen_constructions = set()
    n_events = n_edges = 0
    for case in cases:
        policy = case["policy"]
        tool_names = [t["name"] for t in case["tools"]]
        if len(set(tool_names)) != len(tool_names):
            fail(f"{label}/{case['id']}: duplicate tool names")
        for t in case["tools"]:
            if t["type"] not in TOOL_TYPES:
                fail(f"{label}/{case['id']}: bad tool type {t['type']}")
        event_spans = []
        for span, role, tools in case["gold_events"]:
            if span not in policy:
                fail(f"{label}/{case['id']}: event span not a substring: {span!r}")
            if policy.count(span) != 1:
                fail(f"{label}/{case['id']}: event span not unique: {span!r}")
            if role not in ROLES:
                fail(f"{label}/{case['id']}: bad role {role}")
            if role == "OTHER" and tools:
                fail(f"{label}/{case['id']}: OTHER event {span!r} must have no tools")
            if role != "OTHER" and not tools:
                fail(f"{label}/{case['id']}: event {span!r} needs a governed tool")
            for t in tools:
                if t not in tool_names:
                    fail(f"{label}/{case['id']}: unknown tool {t} for event {span!r}")
            event_spans.append(span)
            n_events += 1
        for edge in case["gold_edges"]:
            if edge["from"] not in event_spans:
                fail(f"{label}/{case['id']}: edge.from not an event: {edge['from']!r}")
            if edge["to"] not in event_spans:
                fail(f"{label}/{case['id']}: edge.to not an event: {edge['to']!r}")
            if edge["from"] == edge["to"]:
                fail(f"{label}/{case['id']}: self-loop edge")
            if edge["relation"] not in GOLD_RELATIONS:
                fail(f"{label}/{case['id']}: bad relation {edge['relation']}")
            if edge["relation"] not in edge.get("acceptable", [edge["relation"]]):
                fail(f"{label}/{case['id']}: acceptable must contain the relation")
            for acc in edge.get("acceptable", []):
                if acc not in GOLD_RELATIONS:
                    fail(f"{label}/{case['id']}: bad acceptable {acc}")
            n_edges += 1
        for grp in case.get("groups", []):
            if grp["type"] not in {"AND", "OR"}:
                fail(f"{label}/{case['id']}: bad group type {grp['type']}")
            for m in grp["members"]:
                if m not in event_spans:
                    fail(f"{label}/{case['id']}: group member not an event: {m!r}")
            if grp["target"] not in event_spans:
                fail(f"{label}/{case['id']}: group target not an event: {grp['target']!r}")
        for code in case["entity_codes"]:
            if code not in policy:
                fail(f"{label}/{case['id']}: entity code {code} not in policy")
        seen_constructions.update(case["constructions"])
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        fail(f"{label}: duplicate case ids")
    return seen_constructions, n_events, n_edges


def pair_universe(case):
    """All ordered (from_event, to_event) candidate pairs over non-descriptive
    events in both directions (a != b). Amendment before LLM unsealing: the
    to-side originally contained only operations/communications, which made
    the nested cond-on-cond gold edges unreachable; it now includes checks and
    state observations as well."""
    side = [s for s, r in [(e[0], e[1]) for e in case["gold_events"]] if r != "OTHER"]
    return [(a, b) for a in side for b in side if a != b]


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
    return {
        "case_id": case["id"],
        "candidate_events": [
            {"source_span": s, "role": r, "governed_tools": list(t)}
            for s, r, t in case["gold_events"]
        ],
        "edges": [
            {"from_span": e["from"], "to_span": e["to"],
             "relation": e["relation"],
             "acceptable": e.get("acceptable", [e["relation"]])}
            for e in case["gold_edges"]
        ],
        "groups": [
            {"type": g["type"], "members": list(g["members"]),
             "target": g["target"]}
            for g in case.get("groups", [])
        ],
        "tool_types": {t["name"]: t["type"] for t in case["tools"]},
        "pair_universe": [{"from": a, "to": b} for a, b in pair_universe(case)],
    }


def relation_inputs_case(case):
    return {
        "case_id": case["id"],
        "events": [
            {"source_span": s, "role": r, "governed_tools": list(t)}
            for s, r, t in case["gold_events"]
        ],
    }


def component_inputs_case(case):
    return {"case_id": case["id"],
            "spans": [s for s, _, _ in case["gold_events"]]}


def make_rename_map(cases):
    rng = random.Random(SEED)
    letters = "abcdefghijklmnopqrstuvwxyz"
    tool_map, entity_map, used = {}, {}, set()

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

    for case in cases:
        for t in case["tools"]:
            tool_map[t["name"]] = new_tool_name()
        for code in case["entity_codes"]:
            entity_map[code] = new_entity_code()
    return tool_map, entity_map


def apply_entity_renames(text, entity_map):
    for code in sorted(entity_map, key=len, reverse=True):
        text = text.replace(code, entity_map[code])
    return text


def renamed_case(case, tool_map, entity_map):
    policy = apply_entity_renames(case["policy"], entity_map)
    tools = [{
        "name": tool_map[t["name"]],
        "description": apply_entity_renames(t["description"], entity_map),
        "input": t["input"], "output": t["output"],
    } for t in case["tools"]]

    def rspan(span):
        s = apply_entity_renames(span, entity_map)
        if s not in policy:
            fail(f"{case['id']}: renamed span not found: {s!r}")
        return s

    events = [(rspan(s), r, [tool_map[g] for g in t])
              for s, r, t in case["gold_events"]]
    edges = [{"from": rspan(e["from"]), "to": rspan(e["to"]),
              "relation": e["relation"],
              "acceptable": e.get("acceptable", [e["relation"]])}
             for e in case["gold_edges"]]
    groups = [{"type": g["type"],
               "members": [rspan(m) for m in g["members"]],
               "target": rspan(g["target"])}
              for g in case.get("groups", [])]
    r_case = dict(case)
    r_case["policy"] = policy
    r_case["tools"] = [{"name": tool_map[t["name"]], "type": t["type"],
                        "description": apply_entity_renames(t["description"], entity_map),
                        "input": t["input"], "output": t["output"]}
                       for t in case["tools"]]
    r_case["gold_events"] = events
    r_case["gold_edges"] = edges
    r_case["groups"] = groups
    r_case["entity_codes"] = [entity_map[c] for c in case["entity_codes"]]
    return r_case


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main():
    constructions_main, ev_m, ed_m = validate(CASES_MAIN, "main")
    constructions_mini, ev_i, ed_i = validate(CASES_MINI, "mini")
    missing = [c for c in REQUIRED_CONSTRUCTIONS
               if c not in constructions_main | constructions_mini]
    if missing:
        fail(f"construction coverage missing: {missing}")

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "frozen"
    out.mkdir(parents=True, exist_ok=True)

    all_cases = CASES_MAIN + CASES_MINI
    tool_map, entity_map = make_rename_map(all_cases)

    files = {}
    for label, cases in (("original", CASES_MAIN), ("mini", CASES_MINI)):
        suffix = "" if label == "original" else "_mini"
        files[f"frozen_cases{suffix}.json"] = [runner_case(c) for c in cases]
        files[f"gold{suffix}.json"] = [gold_case(c) for c in cases]
        files[f"relation_inputs{suffix}.json"] = [relation_inputs_case(c) for c in cases]
        files[f"component_inputs{suffix}.json"] = [component_inputs_case(c) for c in cases]
        renamed = [renamed_case(c, tool_map, entity_map) for c in cases]
        files[f"frozen_cases{suffix}_renamed.json"] = [runner_case(c) for c in renamed]
        files[f"gold{suffix}_renamed.json"] = [gold_case(c) for c in renamed]
        files[f"relation_inputs{suffix}_renamed.json"] = [relation_inputs_case(c) for c in renamed]
        files[f"component_inputs{suffix}_renamed.json"] = [component_inputs_case(c) for c in renamed]

    files["rename_map.json"] = {"seed": SEED, "tools": tool_map,
                                "entities": entity_map}

    manifest = {
        "dataset": "RELATION_GRAPH_v1",
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "seed": SEED,
        "stats": {
            "main": {"cases": len(CASES_MAIN), "events": ev_m, "edges": ed_m},
            "mini": {"cases": len(CASES_MINI), "events": ev_i, "edges": ed_i},
        },
        "minimal_pairs": {},
        "files": {},
    }
    for c in CASES_MAIN + CASES_MINI:
        if c.get("minimal_pair"):
            manifest["minimal_pairs"].setdefault(c["minimal_pair"], []).append(c["id"])

    for name, payload in files.items():
        blob = json.dumps(payload, indent=1, sort_keys=False,
                          ensure_ascii=False).encode("utf-8")
        (out / name).write_bytes(blob)
        manifest["files"][name] = {"sha256": sha256_bytes(blob), "bytes": len(blob)}

    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    n_pairs = sum(len(pair_universe(c)) for c in CASES_MAIN)
    n_pairs_mini = sum(len(pair_universe(c)) for c in CASES_MINI)
    rel_counts = {}
    for c in CASES_MAIN:
        for e in c["gold_edges"]:
            rel_counts[e["relation"]] = rel_counts.get(e["relation"], 0) + 1
    print(f"FREEZE OK: main={len(CASES_MAIN)} cases / {ev_m} events / {ed_m} edges; "
          f"mini={len(CASES_MINI)} cases / {ev_i} events / {ed_i} edges")
    print(f"pair universe: main={n_pairs} ordered pairs ({ed_m} positive), "
          f"mini={n_pairs_mini} ({ed_i} positive)")
    print(f"relation distribution (main): {rel_counts}")
    print(f"minimal pairs: {manifest['minimal_pairs']}")
    print(f"files written to {out} with SHA256 in manifest.json")


if __name__ == "__main__":
    main()

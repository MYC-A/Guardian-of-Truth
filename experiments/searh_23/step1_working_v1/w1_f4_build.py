"""W1 F4 sealed suite builder (v10 architecture validation).

Five NEW domains (apiary / observatory dome / commercial laundry /
vaccination clinic / robotics lab) - disjoint from F, F2, F3.
Frozen BEFORE any F4 inference. Same schema + validation as F3.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
FROZEN = IE / "frozen"

TOOL_STUB = {"input": {"object_id": "string"}, "output": {"status": "string"}}

CASES = [
    {
        "case_id": "i_apiary",
        "domain": "apiary management",
        "family": "sealed_state_gate_recording_event",
        "policy": "Inspect the hive frames in April. Harvest the honey "
                  "only after the queen is seen and the hive log is "
                  "updated. The hive log is a document.",
        "tools": [
            {"name": "inspect_frames",
             "description": "Inspects the frames of one hive.",
             **TOOL_STUB},
            {"name": "harvest_honey",
             "description": "Harvests honey from one hive.",
             **TOOL_STUB},
        ],
        "mentions": [
            ("Inspect the hive frames", "CHECK", "E1"),
            ("the hive frames", "ENTITY", None),
            ("April", "ENTITY", None),
            ("Harvest the honey", "EVENT", "E2"),
            ("the honey", "ENTITY", None),
            ("the queen is seen", "STATE_OR_FACET", "E3"),
            ("the hive log is updated", "EVENT", "E4"),
            ("The hive log", "ARTIFACT", None),
        ],
        "edges": [
            ("E3", "E2", ["STATE_GATE", "PRECONDITION"],
             "Harvest the honey only after the queen is seen"),
            ("E4", "E2", ["PRECONDITION", "ORDER_BEFORE"],
             "only after ... the hive log is updated"),
        ],
        "notes": "coordinated gates: one state + one recording event; "
                 "taxonomy distractor.",
    },
    {
        "case_id": "i_dome",
        "domain": "observatory dome operation",
        "family": "sealed_negated_before_reference",
        "policy": "Do not open the dome before the wind sensor reads "
                  "calm. Close the dome at dawn. Closing is not opening.",
        "tools": [
            {"name": "open_dome",
             "description": "Opens one identified dome.",
             **TOOL_STUB},
            {"name": "close_dome",
             "description": "Closes one identified dome.",
             **TOOL_STUB},
        ],
        "mentions": [
            ("open the dome", "EVENT", "E1"),
            ("the wind sensor reads calm", "STATE_OR_FACET", "E2"),
            ("Close the dome", "EVENT", "E3"),
            ("Closing", "EVENT_REFERENCE", "E3"),
            ("opening", "EVENT_REFERENCE", "E1"),
        ],
        "edges": [
            ("E2", "E1", ["PRECONDITION", "ORDER_BEFORE"],
             "Do not open the dome before the wind sensor reads calm"),
        ],
        "notes": "negated-before (inverted order); identity-negation "
                 "distractor; no relation for Close (time adjunct only).",
    },
    {
        "case_id": "i_laundry",
        "domain": "commercial laundry",
        "family": "sealed_result_state_gate",
        "policy": "Wash the linens at high temperature. Drying may start "
                  "only if the wash cycle has finished. The cycle log "
                  "must record each wash. Drying is not washing.",
        "tools": [
            {"name": "wash_linens",
             "description": "Washes one batch of linens.",
             **TOOL_STUB},
            {"name": "dry_linens",
             "description": "Dries one batch of linens.",
             **TOOL_STUB},
        ],
        "mentions": [
            ("Wash the linens", "EVENT", "E1"),
            ("the linens", "ENTITY", None),
            ("high temperature", "ENTITY", None),
            ("Drying may start", "EVENT", "E2"),
            ("the wash cycle has finished", "STATE_OR_FACET", "E1"),
            ("The cycle log", "ARTIFACT", None),
            ("record each wash", "EVENT", "E4"),
            ("washing", "EVENT_REFERENCE", "E1"),
        ],
        "edges": [
            ("E1", "E2", ["STATE_GATE", "PRECONDITION"],
             "Drying may start only if the wash cycle has finished"),
        ],
        "notes": "modal-subject existential; result-state gate; modal "
                 "recording sentence (mention-only event); "
                 "identity-negation distractor.",
    },
    {
        "case_id": "i_clinic",
        "domain": "vaccination clinic",
        "family": "sealed_unless_response_chain",
        "policy": "Check the vaccine fridge each morning. Administer the "
                  "vaccine unless the fridge temperature exceeds 8 "
                  "degrees, in which case quarantine the vials. The "
                  "incident report must record each quarantine.",
        "tools": [
            {"name": "check_fridge",
             "description": "Checks one vaccine fridge.",
             **TOOL_STUB},
            {"name": "administer_vaccine",
             "description": "Administers one vaccine batch.",
             **TOOL_STUB},
            {"name": "quarantine_vials",
             "description": "Quarantines one set of vials.",
             **TOOL_STUB},
        ],
        "mentions": [
            ("Check the vaccine fridge", "CHECK", "E1"),
            ("the vaccine fridge", "ENTITY", None),
            ("Administer the vaccine", "EVENT", "E2"),
            ("the fridge temperature exceeds 8 degrees",
             "STATE_OR_FACET", "E3"),
            ("quarantine the vials", "EVENT", "E4"),
            ("the vials", "ENTITY", None),
            ("The incident report", "ARTIFACT", None),
            ("record each quarantine", "EVENT", "E5"),
        ],
        "edges": [
            ("E3", "E2", ["EXCEPTION"],
             "Administer the vaccine unless the fridge temperature "
             "exceeds 8 degrees"),
            ("E3", "E4", ["RESPONSE", "ORDER_BEFORE"],
             "in which case quarantine the vials"),
        ],
        "notes": "unless + in-which-case response; numeric threshold "
                 "state; modal recording mention-only event.",
    },
    {
        "case_id": "i_robots",
        "domain": "robotics lab",
        "family": "sealed_gated_sequence_references",
        "policy": "Calibrate the arm before running each demo. Run the "
                  "demo only after the safety cage is closed. The run "
                  "count lists each demo. Running is not calibrating.",
        "tools": [
            {"name": "calibrate_arm",
             "description": "Calibrates one robot arm.",
             **TOOL_STUB},
            {"name": "run_demo",
             "description": "Runs one demo program.",
             **TOOL_STUB},
        ],
        "mentions": [
            ("Calibrate the arm", "EVENT", "E1"),
            ("the arm", "ENTITY", None),
            ("running each demo", "EVENT_REFERENCE", "E2"),
            ("Run the demo", "EVENT", "E2"),
            ("the safety cage is closed", "STATE_OR_FACET", "E3"),
            ("The run count", "ARTIFACT", None),
            ("Running", "EVENT_REFERENCE", "E2"),
            ("calibrating", "EVENT_REFERENCE", "E1"),
        ],
        "edges": [
            ("E1", "E2", ["ORDER_BEFORE", "PRECONDITION"],
             "Calibrate the arm before running each demo"),
            ("E3", "E2", ["STATE_GATE", "PRECONDITION"],
             "Run the demo only after the safety cage is closed"),
        ],
        "notes": "gerund-as-object reference ('before running each demo') "
                 "with an ORDER_BEFORE gold edge; state gate; "
                 "identity-negation distractor.",
    },
]


def build() -> list[dict]:
    out = []
    for spec in CASES:
        policy = spec["policy"]
        for span, _t, _c in spec["mentions"]:
            assert policy.count(span) == 1, \
                f"{spec['case_id']}: span not unique/absent: {span!r}"
        sents = []
        pos = 0
        for s in [x.strip() for x in
                  re.split(r"(?<=[.!?])\s+", policy) if x]:
            start = policy.find(s, pos)
            sents.append({"start": start, "end": start + len(s),
                          "text": s})
            pos = start + len(s)
        mentions = []
        for i, (span, typ, cid) in enumerate(spec["mentions"]):
            start = policy.find(span)
            sent_idx = next((k for k, s in enumerate(sents)
                             if s["start"] <= start < s["end"]), 0)
            mentions.append({"mid": f"m{i+1:02d}", "span": span,
                             "start": start, "end": start + len(span),
                             "type": typ, "cid": cid,
                             "sentence_index": sent_idx})
        cids = sorted({m[2] for m in spec["mentions"] if m[2]})
        canonical = [{"cid": c,
                      "types": sorted({m[1] for m in spec["mentions"]
                                       if m[2] == c})}
                     for c in cids]
        edges = [{"from_cid": a, "to_cid": b, "relation": r[0],
                  "acceptable": r, "evidence": ev}
                 for a, b, r, ev in spec["edges"]]
        out.append({"case_id": spec["case_id"],
                    "original_case_id": spec["case_id"],
                    "domain": spec["domain"], "family": spec["family"],
                    "policy": policy, "sentences": sents,
                    "tools": spec["tools"], "mentions": mentions,
                    "canonical_events": canonical,
                    "entities": [m["span"] for m in mentions
                                 if m["type"] == "ENTITY"],
                    "arguments": [], "semantic_links": [],
                    "normative_edges": edges, "notes": spec["notes"]})
        for e in edges:
            assert e["from_cid"] in cids and e["to_cid"] in cids
    return out


def main() -> None:
    cases = build()
    path = FROZEN / "level_f4_cases.json"
    path.write_text(json.dumps(cases, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (FROZEN / "level_f4_manifest.json").write_text(json.dumps({
        "file": "level_f4_cases.json",
        "sha256": digest,
        "cases": len(cases),
        "gold_edges": sum(len(c["normative_edges"]) for c in cases),
        "frozen": "2026-09-29 (before any F4 inference; F4 never used "
                  "for tuning; validates v10 architecture)",
    }, indent=1) + "\n", encoding="utf-8")
    print(f"froze {len(cases)} cases, "
          f"{sum(len(c['normative_edges']) for c in cases)} gold edges")
    print("sha256", digest[:16])


if __name__ == "__main__":
    main()

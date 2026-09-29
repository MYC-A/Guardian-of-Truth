"""W1 F3 sealed suite builder (fresh domains, frozen BEFORE any inference).

Five new-domain cases exercising: state gates, coordinated
co-preconditions, EXCEPTION (unless), reference chains, repetition
('again'), deontic permission statements, artifact-subject recording
sentences, identity-negation distractors, implicit-order traps (NO
edge), gerund references.

Deterministic offset computation + validation; SHA manifest; freeze.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
FROZEN = IE / "frozen"

TOOL_STUB = {"input": {"object_id": "string"}, "output": {"status": "string"}}

CASES = [
    {
        "case_id": "h_greenhouse",
        "domain": "greenhouse automation",
        "family": "sealed_coordinated_state_gates",
        "policy": "Vent the greenhouse in the morning. Mist the seedlings "
                  "only after the ventilation is complete and the humidity "
                  "log is signed. The humidity log is a document.",
        "tools": [
            {"name": "vent_greenhouse",
             "description": "Vents one identified greenhouse.",
             **TOOL_STUB},
            {"name": "mist_seedlings",
             "description": "Mists the seedlings of one greenhouse.",
             **TOOL_STUB},
        ],
        "mentions": [
            ("Vent the greenhouse", "EVENT", "E1"),
            ("the greenhouse", "ENTITY", None),
            ("the morning", "ENTITY", None),
            ("Mist the seedlings", "EVENT", "E2"),
            ("the seedlings", "ENTITY", None),
            ("the ventilation is complete", "STATE_OR_FACET", "E1"),
            ("the humidity log is signed", "EVENT", "E3"),
            ("The humidity log", "ARTIFACT", None),
        ],
        "edges": [
            ("E1", "E2", ["PRECONDITION", "ORDER_BEFORE"],
             "Mist the seedlings only after the ventilation is complete"),
            ("E3", "E2", ["PRECONDITION", "ORDER_BEFORE"],
             "only after ... the humidity log is signed"),
        ],
        "notes": "coordinated state gates; log-signing as its own event; "
                 "taxonomy distractor.",
    },
    {
        "case_id": "h_bakery",
        "domain": "artisan bakery",
        "family": "sealed_unless_exception_reference_chain",
        "policy": "Proof the dough at room temperature. Bake the loaves "
                  "unless the dough has collapsed, in which case discard "
                  "the batch. Discarding is not baking. The bake sheet "
                  "lists each loaf.",
        "tools": [
            {"name": "proof_dough",
             "description": "Proofs one dough batch.",
             **TOOL_STUB},
            {"name": "bake_loaves",
             "description": "Bakes the loaves of one batch.",
             **TOOL_STUB},
            {"name": "discard_batch",
             "description": "Discards one identified batch.",
             **TOOL_STUB},
        ],
        "mentions": [
            ("Proof the dough", "EVENT", "E1"),
            ("room temperature", "ENTITY", None),
            ("Bake the loaves", "EVENT", "E2"),
            ("the loaves", "ENTITY", None),
            ("the dough has collapsed", "STATE_OR_FACET", "E3"),
            ("discard the batch", "EVENT", "E4"),
            ("the batch", "ENTITY", None),
            ("Discarding", "EVENT_REFERENCE", "E4"),
            ("baking", "EVENT_REFERENCE", "E2"),
            ("The bake sheet", "ARTIFACT", None),
        ],
        "edges": [
            ("E3", "E2", ["EXCEPTION"],
             "Bake the loaves unless the dough has collapsed"),
            ("E3", "E4", ["RESPONSE", "ORDER_BEFORE"],
             "in which case discard the batch"),
        ],
        "notes": "unless-exception; in-which-case response; implicit "
                 "procedure order between Proof and Bake has NO textual "
                 "relation (no edge); identity-negation distractor.",
    },
    {
        "case_id": "h_aquarium",
        "domain": "public aquarium",
        "family": "sealed_check_result_state_gate",
        "policy": "Test the ammonia of tank 6 weekly. The ammonia reading "
                  "must be below 0.5. Feed the fish only if the ammonia "
                  "reading is below 0.5. Feeding is not testing. The care "
                  "log must record each feeding.",
        "tools": [
            {"name": "test_ammonia",
             "description": "Measures the ammonia level of one tank.",
             **TOOL_STUB},
            {"name": "feed_fish",
             "description": "Feeds the fish of one tank.",
             **TOOL_STUB},
        ],
        "mentions": [
            ("Test the ammonia of tank 6", "CHECK", "E1"),
            ("tank 6", "ENTITY", None),
            ("The ammonia reading", "ARTIFACT", None),
            ("Feed the fish", "EVENT", "E2"),
            ("the fish", "ENTITY", None),
            ("the ammonia reading is below 0.5", "STATE_OR_FACET", "E1"),
            ("Feeding", "EVENT_REFERENCE", "E2"),
            ("testing", "EVENT_REFERENCE", "E1"),
            ("The care log", "ARTIFACT", None),
            ("record each feeding", "EVENT", "E4"),
        ],
        "edges": [
            ("E1", "E2", ["STATE_GATE", "PRECONDITION"],
             "Feed the fish only if the ammonia reading is below 0.5"),
        ],
        "notes": "check-result state gate; deontic requirement sentence "
                 "(must be below 0.5, no mention); identity-negation "
                 "distractor; modal recording sentence spawns a "
                 "mention-only event.",
    },
    {
        "case_id": "h_press",
        "domain": "printing press operation",
        "family": "sealed_deontic_permission_state_gates",
        "policy": "Calibrate the press. Printing is permitted only if the "
                  "calibration is current and the ink levels are normal. "
                  "Print the morning edition. The press log confirms each "
                  "calibration.",
        "tools": [
            {"name": "calibrate_press",
             "description": "Calibrates one identified press.",
             **TOOL_STUB},
            {"name": "print_edition",
             "description": "Prints one identified edition.",
             **TOOL_STUB},
        ],
        "mentions": [
            ("Calibrate the press", "EVENT", "E1"),
            ("the press", "ENTITY", None),
            ("Printing", "EVENT_REFERENCE", "E2"),
            ("the calibration is current", "STATE_OR_FACET", "E1"),
            ("the ink levels are normal", "STATE_OR_FACET", "E3"),
            ("Print the morning edition", "EVENT", "E2"),
            ("the morning edition", "ENTITY", None),
            ("each calibration", "EVENT_REFERENCE", "E1"),
            ("The press log", "ARTIFACT", None),
        ],
        "edges": [
            ("E1", "E2", ["STATE_GATE", "PRECONDITION"],
             "Printing is permitted only if the calibration is current"),
            ("E3", "E2", ["STATE_GATE"],
             "only if ... the ink levels are normal"),
        ],
        "notes": "deontic permission statement carries the relation "
                 "(bare-subject reference 'Printing'); coordinated state "
                 "gates; artifact-subject distractor.",
    },
    {
        "case_id": "h_orchard",
        "domain": "orchard management",
        "family": "sealed_repetition_conditional_gate",
        "policy": "Prune the apple trees in March. Spray the orchard after "
                  "pruning. Prune the trees again in August if the growth "
                  "exceeds 20 centimetres. The spray record is a document.",
        "tools": [
            {"name": "prune_trees",
             "description": "Prunes the trees of one orchard.",
             **TOOL_STUB},
            {"name": "spray_orchard",
             "description": "Sprays one identified orchard.",
             **TOOL_STUB},
        ],
        "mentions": [
            ("Prune the apple trees", "EVENT", "E1"),
            ("the apple trees", "ENTITY", None),
            ("March", "ENTITY", None),
            ("Spray the orchard", "EVENT", "E2"),
            ("the orchard", "ENTITY", None),
            ("pruning", "EVENT_REFERENCE", "E1"),
            ("Prune the trees again", "EVENT", "E3"),
            ("the trees", "ENTITY", None),
            ("August", "ENTITY", None),
            ("the growth exceeds 20 centimetres", "STATE_OR_FACET", "E4"),
            ("The spray record", "ARTIFACT", None),
        ],
        "edges": [
            ("E1", "E2", ["ORDER_BEFORE"],
             "Spray the orchard after pruning"),
            ("E4", "E3", ["STATE_GATE", "PRECONDITION"],
             "Prune the trees again in August if the growth exceeds 20 "
             "centimetres"),
        ],
        "notes": "repetition ('again') is a DISTINCT event with no edge to "
                 "its first occurrence; gerund reference; conditional "
                 "state gate; taxonomy distractor.",
    },
]


def build() -> list[dict]:
    out = []
    for spec in CASES:
        policy = spec["policy"]
        # validate single occurrence of each mention span
        for span, _t, _c in spec["mentions"]:
            assert policy.count(span) == 1, \
                f"{spec['case_id']}: span not unique/absent: {span!r}"
        # sentences with offsets
        sents = []
        pos = 0
        for s in [x.strip() for x in
                  __import__("re").split(r"(?<=[.!?])\s+", policy) if x]:
            start = policy.find(s, pos)
            sents.append({"start": start, "end": start + len(s),
                          "text": s})
            pos = start + len(s)
        # mentions with offsets
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
        # validation: edge endpoints exist
        for e in edges:
            assert e["from_cid"] in cids and e["to_cid"] in cids
    return out


def main() -> None:
    cases = build()
    FROZEN.mkdir(parents=True, exist_ok=True)
    path = FROZEN / "level_f3_cases.json"
    path.write_text(json.dumps(cases, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (FROZEN / "level_f3_manifest.json").write_text(json.dumps({
        "file": "level_f3_cases.json",
        "sha256": digest,
        "cases": len(cases),
        "gold_edges": sum(len(c["normative_edges"]) for c in cases),
        "frozen": "2026-09-29 (before any F3 inference; F3 never used "
                  "for tuning)",
    }, indent=1) + "\n", encoding="utf-8")
    print(f"froze {len(cases)} cases, "
          f"{sum(len(c['normative_edges']) for c in cases)} gold edges")
    print("sha256", digest[:16])
    for c in cases:
        print(f"  {c['case_id']}: {len(c['mentions'])} mentions, "
              f"{len(c['normative_edges'])} edges, "
              f"policy {len(c['policy'])} chars")


if __name__ == "__main__":
    main()

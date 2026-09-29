"""F5 SEALED SUITE builder — Event Normalization Generalization phase.

19 policies (6 known-mechanism + 6 recombination/counterfactual + 7
genuinely-new constructions), frozen BEFORE any F5 inference (directive
§11-§12). Plus:
  - F5_CF : 4 counterfactual minimal-pair twins (identity flip checks)
  - F5_REN: renamed variant of 6 representative cases (rename invariance)

Gold conventions (frozen here, documented in manifest):
  - mention: (span, type, cid) — cid None = entity/artifact/junk
    (NON_EVENT). SAME cid across mentions = SAME canonical event.
  - Passive voice facet ('X is cleaned') shares the cid of 'Clean X'
    (voice facet of one rule — W1 convention). Adjectival result STATE
    ('X is clean', 'reads calm') gets its OWN cid (STATE observation).
  - action vs check-of-action vs recording-of-action: three cids
    (RELATED_BUT_DIFFERENT at pair level).
  - 'again' / explicit repetition: separate occurrence = separate cid.
  - pair labels DERIVED: same cid=SAME_EVENT; gold-edge endpoints (or
    check/record/about relations annotated via 'related_pairs') =
    RELATED_BUT_DIFFERENT; else DIFFERENT_EVENT. Explicit AMBIGUOUS list
    for genuinely undecidable pairs.

Run: python en_f5_build.py   (writes frozen/ + manifest, NO inference)
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
FROZEN = HERE / "f5_frozen"
FROZEN.mkdir(parents=True, exist_ok=True)

TOOL_STUB = {"input": {"object_id": "string"},
             "output": {"status": "string"}}

M_EVENT = "EVENT"
M_REF = "EVENT_REFERENCE"
M_STATE = "STATE_OR_FACET"
M_CHECK = "CHECK"
M_ENT = "ENTITY"
M_ART = "ARTIFACT"

CASES = []


def case(cid, domain, family, policy, tools, mentions, edges, notes="",
         related_pairs=None, ambiguous_pairs=None):
    CASES.append({
        "case_id": cid, "domain": domain, "family": family,
        "policy": policy, "tools": tools,
        "mentions": [list(m) for m in mentions],
        "normative_edges": [list(e) for e in edges],
        "related_pairs": [list(p) for p in (related_pairs or [])],
        "ambiguous_pairs": [list(p) for p in (ambiguous_pairs or [])],
        "notes": notes})


# ------------------------------------------------------------- K (known)
case(
    "k_lighthouse", "lighthouse maintenance",
    "known_coordinated_state_gates",
    "Clean the lens housing each March. Relight the beacon only after "
    "the lens housing is cleaned and the keeper's entry is filed. The "
    "keeper's entry is a document.",
    [{"name": "clean_lens", "description": "Cleans the lens housing of "
      "one lighthouse.", **TOOL_STUB},
     {"name": "relight_beacon", "description": "Relights the beacon of "
      "one lighthouse.", **TOOL_STUB},
     {"name": "file_entry", "description": "Files the keeper's entry "
      "for one lighthouse.", **TOOL_STUB}],
    [("Clean the lens housing", M_EVENT, "E1"),
     ("the lens housing", M_ENT, None),
     ("each March", M_ENT, None),
     ("Relight the beacon", M_EVENT, "E2"),
     ("the lens housing is cleaned", M_STATE, "E1"),
     ("the keeper's entry is filed", M_EVENT, "E3"),
     ("The keeper's entry", M_ART, None),
     ("a document", M_ENT, None)],
    [("E1", "E2", ["STATE_GATE", "PRECONDITION"],
      "Relight the beacon only after the lens housing is cleaned and "
      "the keeper's entry is filed"),
     ("E3", "E2", ["PRECONDITION", "ORDER_BEFORE"],
      "the keeper's entry is filed")],
    "coordinated gates: state + recording event; taxonomy distractor; "
    "passive facet of E1 shares cid.")

case(
    "k_kiln", "ceramics studio kiln firing",
    "known_check_result_state_gate",
    "Fire the glazed ware in kiln 2. Unload the kiln only after a "
    "shrinkage check has passed. Firing is permitted before noon. The "
    "firing log lists every completed firing.",
    [{"name": "fire_kiln", "description": "Fires glazed ware in one "
      "kiln.", **TOOL_STUB},
     {"name": "unload_kiln", "description": "Unloads one kiln.",
      **TOOL_STUB},
     {"name": "run_shrinkage_check", "description": "Runs a shrinkage "
      "check on one batch of ware.", **TOOL_STUB}],
    [("Fire the glazed ware", M_EVENT, "E1"),
     ("the glazed ware", M_ENT, None),
     ("kiln 2", M_ENT, None),
     ("Unload the kiln", M_EVENT, "E2"),
     ("a shrinkage check has passed", M_STATE, "E3"),
     ("a shrinkage check", M_CHECK, None),
     ("Firing is permitted", M_EVENT, "E1"),
     ("before noon", M_ENT, None),
     ("The firing log", M_ART, None),
     ("every completed firing", M_REF, None)],
    [("E3", "E2", ["STATE_GATE", "PRECONDITION"],
      "Unload the kiln only after a shrinkage check has passed")],
    "check-result state gate; deontic permission with bare-subject "
    "reference ('Firing is permitted' -> E1); artifact-subject junk "
    "sentence.",
    related_pairs=[("E1", "E3")]
)

case(
    "k_ferry", "maritime ferry operations",
    "known_unless_in_which_case",
    "Sail the 07:00 crossing with a full crew. Cancel the crossing "
    "unless the visibility exceeds one mile; in which case the captain "
    "must notify the port office.",
    [{"name": "sail_crossing", "description": "Sails one scheduled "
      "crossing.", **TOOL_STUB},
     {"name": "cancel_crossing", "description": "Cancels one scheduled "
      "crossing.", **TOOL_STUB},
     {"name": "notify_port", "description": "Notifies the port office "
      "about one crossing.", **TOOL_STUB}],
    [("Sail the 07:00 crossing", M_EVENT, "E1"),
     ("the 07:00 crossing", M_ENT, None),
     ("a full crew", M_ENT, None),
     ("Cancel the crossing", M_EVENT, "E2"),
     ("the visibility exceeds one mile", M_STATE, "E3"),
     ("the captain", M_ENT, None),
     ("notify the port office", M_EVENT, "E4")],
    [("E3", "E2", ["STATE_GATE", "PRECONDITION"],
      "Cancel the crossing unless the visibility exceeds one mile"),
     ("E2", "E1", ["EXCEPTION"],
      "Cancel the crossing unless the visibility exceeds one mile"),
     ("E4", "E2", ["RESPONSE"],
      "in which case the captain must notify the port office")],
    "unless-exception + in-which-case response (W1 F3 h_bakery class, "
    "new domain): visibility state gates the cancellation; notify "
    "responds to the cancellation branch.")

case(
    "k_icerink", "ice rink resurfacing",
    "known_negated_before_repetition",
    "Do not resurface the rink before the ice temperature stabilizes. "
    "Measure the ice temperature each morning. If the reading drifts, "
    "resurface the rink again after a second measurement.",
    [{"name": "resurface_rink", "description": "Resurfaces one ice "
      "rink.", **TOOL_STUB},
     {"name": "measure_temp", "description": "Measures the ice "
      "temperature of one rink.", **TOOL_STUB}],
    [("resurface the rink", M_EVENT, "E1"),
     ("the ice temperature", M_ENT, None),
     ("the ice temperature stabilizes", M_STATE, "E2"),
     ("Measure the ice temperature", M_CHECK, "E3"),
     ("each morning", M_ENT, None),
     ("the reading drifts", M_STATE, "E4"),
     ("resurface the rink again", M_EVENT, "E5"),
     ("a second measurement", M_REF, "E3")],
    [("E2", "E1", ["STATE_GATE", "PRECONDITION"],
      "Do not resurface the rink before the ice temperature stabilizes"),
     ("E3", "E5", ["PRECONDITION", "ORDER_BEFORE"],
      "resurface the rink again after a second measurement")],
    "negated-before inversion (E2 gates E1); 'again' = distinct "
    "occurrence E5; gerund/nominal ref 'a second measurement' -> E3.",
    related_pairs=[("E1", "E5")]
)

case(
    "k_mushroom", "mushroom farm cultivation",
    "known_gerund_implicit_order_trap",
    "Pasteurize the substrate. Spawn the beds after pasteurizing. "
    "Harvest the flush when the caps open. Sterilization is not "
    "pasteurization.",
    [{"name": "pasteurize_substrate", "description": "Pasteurizes one "
      "batch of substrate.", **TOOL_STUB},
     {"name": "spawn_beds", "description": "Spawns one set of beds.",
      **TOOL_STUB},
     {"name": "harvest_flush", "description": "Harvests one flush of "
      "mushrooms.", **TOOL_STUB}],
    [("Pasteurize the substrate", M_EVENT, "E1"),
     ("the substrate", M_ENT, None),
     ("Spawn the beds", M_EVENT, "E2"),
     ("pasteurizing", M_REF, "E1"),
     ("Harvest the flush", M_EVENT, "E3"),
     ("the caps open", M_STATE, "E4"),
     ("Sterilization", M_REF, None),
     ("pasteurization", M_REF, None)],
    [("E1", "E2", ["PRECONDITION", "ORDER_BEFORE"],
      "Spawn the beds after pasteurizing"),
     ("E4", "E3", ["STATE_GATE"],
      "Harvest the flush when the caps open")],
    "gerund reference (SAME as imperative); identity-negation "
    "distractor; NOTE: 'Sterilize' never appears as an event - the "
    "negation mentions two nominalizations only.")

case(
    "k_brewery", "brewery sanitation",
    "known_recording_containment",
    "Sanitize the fermenters. The sanitation log confirms each "
    "sanitized fermenter. Bottle the batch only after the sanitation "
    "log is complete.",
    [{"name": "sanitize_fermenter", "description": "Sanitizes one "
      "fermenter.", **TOOL_STUB},
     {"name": "bottle_batch", "description": "Bottles one batch of "
      "beer.", **TOOL_STUB}],
    [("Sanitize the fermenters", M_EVENT, "E1"),
     ("the fermenters", M_ENT, None),
     ("The sanitation log", M_ART, None),
     ("each sanitized fermenter", M_REF, None),
     ("Bottle the batch", M_EVENT, "E2"),
     ("the sanitation log is complete", M_STATE, "E3")],
    [("E3", "E2", ["STATE_GATE", "PRECONDITION"],
      "Bottle the batch only after the sanitation log is complete")],
    "recording-containment: 'the sanitation log confirms...' is an "
    "artifact-subject junk sentence; log-completeness state gates "
    "bottling (E3 own cid, RELATED to E1).",
    related_pairs=[("E1", "E3")]
)

# --------------------------------------------- R (recombination / CF)
case(
    "r_fountain", "public fountain maintenance",
    "rc_active_passive_nominal_chain",
    "Drain the fountain basin. Scrub the tiles while the basin is "
    "drained. The draining is logged by the maintenance desk. Refill "
    "the basin only after scrubbing.",
    [{"name": "drain_basin", "description": "Drains one fountain "
      "basin.", **TOOL_STUB},
     {"name": "scrub_tiles", "description": "Scrubs the tiles of one "
      "fountain basin.", **TOOL_STUB},
     {"name": "refill_basin", "description": "Refills one fountain "
      "basin.", **TOOL_STUB}],
    [("Drain the fountain basin", M_EVENT, "E1"),
     ("the fountain basin", M_ENT, None),
     ("Scrub the tiles", M_EVENT, "E2"),
     ("the tiles", M_ENT, None),
     ("the basin is drained", M_STATE, "E1"),
     ("The draining", M_REF, "E1"),
     ("the maintenance desk", M_ENT, None),
     ("Refill the basin", M_EVENT, "E3"),
     ("scrubbing", M_REF, "E2")],
    [("E1", "E2", ["STATE_GATE", "PRECONDITION"],
      "Scrub the tiles while the basin is drained"),
     ("E2", "E3", ["PRECONDITION", "ORDER_BEFORE"],
      "Refill the basin only after scrubbing")],
    "active/passive/nominal chain all -> E1 (SAME identity stress); "
    "'is logged by' = recording sentence about E1 (no cid: junk "
    "clause, the logging is performed by desk).")

case(
    "r_ewaste", "e-waste dismantling line",
    "rc_action_check_record_triad",
    "Test each donated board. Verify that each board passed the test "
    "before dismantling it. Record the test result in the intake "
    "sheet. Dismantle only verified boards.",
    [{"name": "test_board", "description": "Tests one donated "
      "board.", **TOOL_STUB},
     {"name": "verify_result", "description": "Verifies the test "
      "result of one board.", **TOOL_STUB},
     {"name": "record_result", "description": "Records one test result "
      "in the intake sheet.", **TOOL_STUB},
     {"name": "dismantle_board", "description": "Dismantles one "
      "board.", **TOOL_STUB}],
    [("Test each donated board", M_CHECK, "E1"),
     ("each donated board", M_ENT, None),
     ("each board passed the test", M_STATE, "E2"),
     ("dismantling it", M_REF, "E3"),
     ("Record the test result", M_EVENT, "E4"),
     ("the test result", M_REF, "E1"),
     ("the intake sheet", M_ART, None),
     ("Dismantle", M_EVENT, "E3"),
     ("verified boards", M_REF, "E2")],
    [("E2", "E3", ["STATE_GATE", "PRECONDITION"],
      "Verify that each board passed the test before dismantling it")],
    "action/check/record TRIAD: test (E1) vs passed-state (E2) vs "
    "record (E4) - three distinct events, all RELATED; 'dismantling "
    "it' gerund ref -> E3; 'the test result' nominal ref -> E1.",
    related_pairs=[("E1", "E2"), ("E1", "E4"), ("E2", "E4")]
)

case(
    "r_verticalfarm", "vertical farm operations",
    "rc_same_predicate_split_arguments_time",
    "Pollinate the tomato towers each Monday. Pollinate the basil "
    "racks each Thursday. Harvest the basil after the third "
    "pollination of the basil racks. Harvest the basil again after a "
    "further week.",
    [{"name": "pollinate_tower", "description": "Pollinates one tomato "
      "tower.", **TOOL_STUB},
     {"name": "pollinate_rack", "description": "Pollinates one basil "
      "rack.", **TOOL_STUB},
     {"name": "harvest_crop", "description": "Harvests one crop "
      "batch.", **TOOL_STUB}],
    [("Pollinate the tomato towers", M_EVENT, "E1"),
     ("the tomato towers", M_ENT, None),
     ("each Monday", M_ENT, None),
     ("Pollinate the basil racks", M_EVENT, "E2"),
     ("the basil racks", M_ENT, None),
     ("each Thursday", M_ENT, None),
     ("Harvest the basil", M_EVENT, "E3"),
     ("the basil", M_ENT, None),
     ("the third pollination of the basil racks", M_REF, "E2"),
     ("Harvest the basil again", M_EVENT, "E4"),
     ("a further week", M_ENT, None)],
    [("E2", "E3", ["PRECONDITION", "ORDER_BEFORE"],
      "Harvest the basil after the third pollination of the basil "
      "racks")],
    "same predicate, different object (E1 vs E2 - DIFFERENT events, "
    "same actor); same predicate+object, different time (E3 vs E4 "
    "'again'); nested nominalization ref.",
    related_pairs=[("E1", "E2"), ("E3", "E4")]
)

case(
    "r_helicopter", "mountain rescue helicopter ops",
    "rc_polarity_flip",
    "Inspect the hoist cable before every mission. Replace the hoist "
    "cable if the inspection finds fraying. Do not schedule a mission "
    "before the hoist cable is replaced.",
    [{"name": "inspect_hoist", "description": "Inspects the hoist "
      "cable of one helicopter.", **TOOL_STUB},
     {"name": "replace_hoist", "description": "Replaces the hoist "
      "cable of one helicopter.", **TOOL_STUB},
     {"name": "schedule_mission", "description": "Schedules one rescue "
      "mission.", **TOOL_STUB}],
    [("Inspect the hoist cable", M_CHECK, "E1"),
     ("the hoist cable", M_ENT, None),
     ("every mission", M_ENT, None),
     ("Replace the hoist cable", M_EVENT, "E2"),
     ("the inspection finds fraying", M_STATE, "E3"),
     ("a mission", M_ENT, None),
     ("the hoist cable is replaced", M_STATE, "E2"),
     ("schedule a mission", M_EVENT, "E4")],
    [("E1", "E4", ["PRECONDITION", "ORDER_BEFORE"],
      "Inspect the hoist cable before every mission"),
     ("E3", "E2", ["STATE_GATE", "PRECONDITION"],
      "Replace the hoist cable if the inspection finds fraying"),
     ("E2", "E4", ["STATE_GATE", "PRECONDITION"],
      "Do not schedule a mission before the hoist cable is replaced")],
    "polarity: negated-before (E2 gates E4 via 'Do not ... before'); "
    "conditional response (E3 -> E2); passive facet 'is replaced' "
    "shares E2; check (E1) vs its finding-state (E3) distinct.",
    related_pairs=[("E1", "E3")]
)

case(
    "r_paper", "archival paper conservation",
    "rc_planned_vs_performed",
    "Deacidify the folios in batches. Each batch was deacidified last "
    "quarter. Humidify the folios before flattening. The humidification "
    "plan requires a pilot batch first.",
    [{"name": "deacidify_folio", "description": "Deacidifies one batch "
      "of folios.", **TOOL_STUB},
     {"name": "humidify_folio", "description": "Humidifies one batch "
      "of folios.", **TOOL_STUB},
     {"name": "flatten_folio", "description": "Flattens one batch of "
      "folios.", **TOOL_STUB}],
    [("Deacidify the folios", M_EVENT, "E1"),
     ("the folios", M_ENT, None),
     ("Each batch was deacidified", M_EVENT, "E2"),
     ("last quarter", M_ENT, None),
     ("Humidify the folios", M_EVENT, "E3"),
     ("flattening", M_REF, "E4"),
     ("The humidification plan", M_ART, None),
     ("a pilot batch", M_ENT, None)],
    [("E3", "E4", ["PRECONDITION", "ORDER_BEFORE"],
      "Humidify the folios before flattening")],
    "planned/required (E1) vs observed historical (E2) - same "
    "predicate, distinct events; gerund ref 'flattening' -> E4; "
    "artifact 'humidification plan' with modal junk clause.",
    related_pairs=[("E1", "E2")]
)

case(
    "r_solarfarm", "solar farm maintenance",
    "rc_gate_by_state_vs_gate_by_check",
    "Wash the panel strings after rainfall. Clean the inverters only "
    "if the thermal camera flags overheating. Flagging is performed by "
    "the duty technician.",
    [{"name": "wash_panels", "description": "Washes one panel "
      "string.", **TOOL_STUB},
     {"name": "clean_inverter", "description": "Cleans one "
      "inverter.", **TOOL_STUB},
     {"name": "flag_overheating", "description": "Flags one overheating "
      "inverter.", **TOOL_STUB}],
    [("Wash the panel strings", M_EVENT, "E1"),
     ("the panel strings", M_ENT, None),
     ("rainfall", M_ENT, None),
     ("Clean the inverters", M_EVENT, "E2"),
     ("the thermal camera", M_ENT, None),
     ("flags overheating", M_CHECK, "E3"),
     ("overheating", M_STATE, None),
     ("Flagging", M_REF, "E3"),
     ("the duty technician", M_ENT, None)],
    [("E3", "E2", ["STATE_GATE", "PRECONDITION"],
      "Clean the inverters only if the thermal camera flags "
      "overheating")],
    "state-gate vs check-gate contrast; nominal 'Flagging' -> E3; "
    "passive agent clause junk.",
    related_pairs=[("E1", "E2")]
)

# ------------------------------------------------------------- N (new)
case(
    "n_chemistry", "school chemistry lab",
    "new_numeric_threshold_alternatives",
    "Neutralize the acid bath if the pH falls below 5.0 or rises "
    "above 9.0. Either drain the bath or refill it with buffer within "
    "ten minutes of neutralizing.",
    [{"name": "neutralize_bath", "description": "Neutralizes one acid "
      "bath.", **TOOL_STUB},
     {"name": "drain_bath", "description": "Drains one acid bath.",
      **TOOL_STUB},
     {"name": "refill_buffer", "description": "Refills one acid bath "
      "with buffer.", **TOOL_STUB}],
    [("Neutralize the acid bath", M_EVENT, "E1"),
     ("the acid bath", M_ENT, None),
     ("the pH falls below 5.0", M_STATE, "E2"),
     ("rises above 9.0", M_STATE, "E3"),
     ("drain the bath", M_EVENT, "E4"),
     ("refill it with buffer", M_EVENT, "E5"),
     ("buffer", M_ENT, None),
     ("ten minutes", M_ENT, None),
     ("neutralizing", M_REF, "E1")],
    [("E2", "E1", ["STATE_GATE"],
      "Neutralize the acid bath if the pH falls below 5.0"),
     ("E3", "E1", ["STATE_GATE"],
      "or rises above 9.0"),
     ("E1", "E4", ["RESPONSE", "ORDER_BEFORE"],
      "Either drain the bath or refill it with buffer within ten "
      "minutes of neutralizing"),
     ("E1", "E5", ["RESPONSE", "ORDER_BEFORE"],
      "Either drain the bath or refill it with buffer within ten "
      "minutes of neutralizing")],
    "numeric thresholds as gates; either/or ALTERNATIVE gates (E4/E5 "
    "not related to each other - no edge between them); pronoun 'it' "
    "-> the bath; gerund 'neutralizing' -> E1.")

case(
    "n_stage", "theater stage rigging",
    "new_multi_actor_anaphora_chain",
    "The rigging operator inspects the fly bars each week. The "
    "supervisor countersigns it. This countersignature is required "
    "before the first rehearsal. It expires after thirty days.",
    [{"name": "inspect_bars", "description": "Inspects the fly bars of "
      "one stage.", **TOOL_STUB},
     {"name": "countersign", "description": "Countersigns one "
      "inspection record.", **TOOL_STUB},
     {"name": "hold_rehearsal", "description": "Holds one rehearsal.",
      **TOOL_STUB}],
    [("The rigging operator", M_ENT, None),
     ("inspects the fly bars", M_CHECK, "E1"),
     ("the fly bars", M_ENT, None),
     ("each week", M_ENT, None),
     ("The supervisor", M_ENT, None),
     ("countersigns it", M_EVENT, "E2"),
     ("This countersignature", M_REF, "E2"),
     ("the first rehearsal", M_ENT, None),
     ("It expires", M_STATE, "E2"),
     ("thirty days", M_ENT, None)],
    [("E2", "E1", ["RESPONSE", "ORDER_BEFORE"],
      "The supervisor countersigns it")],
    "multi-actor (operator inspects, supervisor countersigns); "
    "pronoun 'it' -> inspection; 'This countersignature' -> E2; 'It "
    "expires' state of E2's artifact-event; 'before the first "
    "rehearsal' = embedded temporal NP, NOT an event mention.",
    related_pairs=[("E1", "E2")]
)

case(
    "n_vetsurgery", "veterinary surgery clinic",
    "new_temporal_qualifier_exception_chain",
    "Admit the animal within two hours of the referral. Sedate the "
    "animal unless the heart rate exceeds 240; in which case postpone "
    "the sedation and notify the surgeon; otherwise proceed with the "
    "sedation.",
    [{"name": "admit_animal", "description": "Admits one animal.",
      **TOOL_STUB},
     {"name": "sedate_animal", "description": "Sedates one animal.",
      **TOOL_STUB},
     {"name": "notify_surgeon", "description": "Notifies the surgeon "
      "about one animal.", **TOOL_STUB}],
    [("Admit the animal", M_EVENT, "E1"),
     ("the animal", M_ENT, None),
     ("two hours", M_ENT, None),
     ("the referral", M_ENT, None),
     ("Sedate the animal", M_EVENT, "E2"),
     ("the heart rate exceeds 240", M_STATE, "E3"),
     ("postpone the sedation", M_EVENT, "E4"),
     ("the sedation", M_REF, "E2"),
     ("notify the surgeon", M_EVENT, "E5"),
     ("the surgeon", M_ENT, None)],
    [("E3", "E2", ["EXCEPTION", "STATE_GATE"],
      "Sedate the animal unless the heart rate exceeds 240"),
     ("E4", "E2", ["EXCEPTION"],
      "in which case postpone the sedation"),
     ("E5", "E2", ["RESPONSE"],
      "and notify the surgeon")],
    "temporal qualifier (within two hours); exception chain "
    "unless/in-which-case/otherwise; 'postpone the sedation' is a "
    "DISTINCT event (E4) related to E2 — not the same occurrence.",
    related_pairs=[("E2", "E4")]
)

case(
    "n_3dprint", "3D print farm",
    "new_nested_nominalization",
    "Calibrate the nozzles daily. The completion of the calibration of "
    "the nozzles unlocks the morning queue. Log the nozzle count "
    "before each print run.",
    [{"name": "calibrate_nozzle", "description": "Calibrates one "
      "nozzle.", **TOOL_STUB},
     {"name": "unlock_queue", "description": "Unlocks one print "
      "queue.", **TOOL_STUB},
     {"name": "log_count", "description": "Logs the nozzle count for "
      "one print run.", **TOOL_STUB}],
    [("Calibrate the nozzles", M_EVENT, "E1"),
     ("the nozzles", M_ENT, None),
     ("The completion of the calibration of the nozzles", M_STATE,
      "E2"),
     ("the morning queue", M_ENT, None),
     ("Log the nozzle count", M_EVENT, "E3"),
     ("the nozzle count", M_REF, None),
     ("each print run", M_ENT, None),
     ("unlocks the morning queue", M_EVENT, "E4")],
    [("E2", "E4", ["STATE_GATE", "PRECONDITION"],
      "The completion of the calibration of the nozzles unlocks the "
      "morning queue")],
    "nested nominalization ('completion of the calibration of the "
    "nozzles') = completion-state E2, distinct from E1 but RELATED; "
    "'Log the nozzle count' recording event E3 with temporal NP; "
    "subjunctive 'unlocks the morning queue' verb-phrase event E4 "
    "inside the evidence clause.",
    related_pairs=[("E1", "E2"), ("E1", "E3"), ("E1", "E4")],
)

case(
    "n_wildlife", "wildlife rehabilitation clinic",
    "new_artifact_flow_elliptical",
    "Weigh each rescued raptor on intake. Record the weight in the "
    "clinic ledger. The ledger is archived weekly by the registrar. "
    "Feed the raptors twice daily and log any refusals.",
    [{"name": "weigh_raptor", "description": "Weighs one rescued "
      "raptor.", **TOOL_STUB},
     {"name": "record_weight", "description": "Records one weight in "
      "the clinic ledger.", **TOOL_STUB},
     {"name": "feed_raptor", "description": "Feeds one raptor.",
      **TOOL_STUB}],
    [("Weigh each rescued raptor", M_CHECK, "E1"),
     ("each rescued raptor", M_ENT, None),
     ("Record the weight", M_EVENT, "E2"),
     ("the weight", M_REF, "E1"),
     ("the clinic ledger", M_ART, None),
     ("The ledger is archived", M_EVENT, "E3"),
     ("the registrar", M_ENT, None),
     ("Feed the raptors", M_EVENT, "E4"),
     ("the raptors", M_ENT, None),
     ("twice daily", M_ENT, None),
     ("log any refusals", M_EVENT, "E5"),
     ("any refusals", M_REF, None)],
    [("E1", "E2", ["RESPONSE", "ORDER_BEFORE"],
      "Weigh each rescued raptor on intake. Record the weight")],
    "artifact flow weigh->record->archive (three distinct events, "
    "chain of RELATED pairs); elliptical coordination 'Feed ... and "
    "log any refusals' (E4 and E5 coordinated, NO edge between them).",
    related_pairs=[("E2", "E3"), ("E4", "E5")]
)

case(
    "n_groundwater", "groundwater remediation site",
    "new_observed_vs_required_passive_chain",
    "The monitoring well was sampled last May. Sample the well again "
    "this quarter. Pump the treatment cell only after the sample is "
    "analyzed by the lab.",
    [{"name": "sample_well", "description": "Samples one monitoring "
      "well.", **TOOL_STUB},
     {"name": "pump_cell", "description": "Pumps one treatment "
      "cell.", **TOOL_STUB},
     {"name": "analyze_sample", "description": "Analyzes one sample.",
      **TOOL_STUB}],
    [("The monitoring well was sampled", M_EVENT, "E1"),
     ("The monitoring well", M_ENT, None),
     ("last May", M_ENT, None),
     ("Sample the well again", M_EVENT, "E2"),
     ("this quarter", M_ENT, None),
     ("Pump the treatment cell", M_EVENT, "E3"),
     ("the sample is analyzed by the lab", M_STATE, "E4"),
     ("the sample", M_REF, None),
     ("the lab", M_ENT, None)],
    [("E4", "E3", ["STATE_GATE", "PRECONDITION"],
      "Pump the treatment cell only after the sample is analyzed by "
      "the lab")],
    "observed historical ('was sampled', E1) vs required repeat "
    "('Sample ... again', E2); passive chain; 'the sample' nominal "
    "ref to the sampling event.",
    related_pairs=[("E1", "E2"), ("E2", "E4")]
)

case(
    "n_hoodclean", "commercial kitchen hood cleaning",
    "new_modal_mixed_alternative_gates",
    "Degrease the hood quarterly. The extractor fans may be removed "
    "for cleaning. Cleaning must be documented. Book the kitchen only "
    "if either the hood certificate is current or a supervisor "
    "waives the requirement.",
    [{"name": "degrease_hood", "description": "Degreases one kitchen "
      "hood.", **TOOL_STUB},
     {"name": "remove_fans", "description": "Removes the extractor "
      "fans of one kitchen.", **TOOL_STUB},
     {"name": "book_kitchen", "description": "Books one kitchen for "
      "an event.", **TOOL_STUB},
     {"name": "waive_requirement", "description": "Waives the hood "
      "certificate requirement for one kitchen.", **TOOL_STUB}],
    [("Degrease the hood", M_EVENT, "E1"),
     ("the hood", M_ENT, None),
     ("quarterly", M_ENT, None),
     ("The extractor fans", M_ENT, None),
     ("be removed for cleaning", M_EVENT, "E2"),
     ("cleaning", M_REF, "E5"),
     ("Cleaning must be documented", M_STATE, "E3"),
     ("Book the kitchen", M_EVENT, "E4"),
     ("the kitchen", M_ENT, None),
     ("the hood certificate is current", M_STATE, "E6"),
     ("a supervisor", M_ENT, None),
     ("waives the requirement", M_EVENT, "E7")],
    [("E6", "E4", ["STATE_GATE", "PRECONDITION"],
      "Book the kitchen only if either the hood certificate is "
      "current"),
     ("E7", "E4", ["EXCEPTION"],
      "or a supervisor waives the requirement")],
    "modal mix (may/must); 'either A or B' alternative gates - E6 and "
    "E7 are NOT related to each other (no edge between them); "
    "'cleaning' gerund -> E5 (the cleaning the removal serves); "
    "documentation state E3 related to E5; 'Cleaning must be "
    "documented' second mention of the same string is capital-cased "
    "(distinct span).",
    related_pairs=[("E1", "E5"), ("E5", "E3"), ("E2", "E5")]
)

case(
    "n_maple", "maple syrup harvesting",
    "new_state_chain_pronoun",
    "Tap the maples in February. Boil the sap when the sugar content "
    "exceeds two percent. Filter the syrup after boiling it. The "
    "filtering is repeated if the syrup remains cloudy.",
    [{"name": "tap_maple", "description": "Taps one maple tree.",
      **TOOL_STUB},
     {"name": "boil_sap", "description": "Boils one batch of sap.",
      **TOOL_STUB},
     {"name": "filter_syrup", "description": "Filters one batch of "
      "syrup.", **TOOL_STUB}],
    [("Tap the maples", M_EVENT, "E1"),
     ("the maples", M_ENT, None),
     ("in February", M_ENT, None),
     ("Boil the sap", M_EVENT, "E2"),
     ("the sap", M_ENT, None),
     ("the sugar content exceeds two percent", M_STATE, "E3"),
     ("Filter the syrup", M_EVENT, "E4"),
     ("the syrup", M_ENT, None),
     ("boiling it", M_REF, "E2"),
     ("The filtering is repeated", M_EVENT, "E5"),
     ("the syrup remains cloudy", M_STATE, "E6")],
    [("E3", "E2", ["STATE_GATE"],
      "Boil the sap when the sugar content exceeds two percent"),
     ("E2", "E4", ["PRECONDITION", "ORDER_BEFORE"],
      "Filter the syrup after boiling it"),
     ("E6", "E5", ["STATE_GATE"],
      "The filtering is repeated if the syrup remains cloudy")],
    "pronoun in gerund ('boiling it' -> E2); repetition-of-filtering "
    "= E5 distinct from E4; state chains.",
    related_pairs=[("E4", "E5")]
)

# ------------------------------------------------------------- CF twins
# Counterfactual minimal pairs (directive §13): each pair flips ONE
# semantic factor; the identity layer must flip its SAME decision.
CF_TWINS = [
    {
        "twin_id": "cf_filter",
        "mechanism": "action_vs_check_of_action",
        "a": {"policy": "Inspect the filter. Processing may continue "
                        "after the filter is inspected.",
              "focus": ("Inspect the filter", "the filter is inspected"),
              "expected": "SAME_EVENT"},
        "b": {"policy": "Inspect the filter. Processing may continue "
                        "after an operator verifies that the filter "
                        "was inspected.",
              "focus": ("Inspect the filter",
                        "verifies that the filter was inspected"),
              "expected": "RELATED_BUT_DIFFERENT"},
    },
    {
        "twin_id": "cf_otters",
        "mechanism": "same_predicate_different_object",
        "a": {"policy": "Feed the otters. After the otters are fed, "
                        "record the feeding time.",
              "focus": ("Feed the otters", "the otters are fed"),
              "expected": "SAME_EVENT"},
        "b": {"policy": "Feed the otters. Feed the red pandas. Record "
                        "both feeding times.",
              "focus": ("Feed the otters", "Feed the red pandas"),
              "expected": "DIFFERENT_EVENT"},
    },
    {
        "twin_id": "cf_vessel",
        "mechanism": "action_vs_recording_of_action",
        "a": {"policy": "The vessel is cleaned after each batch. "
                        "After cleaning the vessel, notify the shift "
                        "lead.",
              "focus": ("The vessel is cleaned", "cleaning the vessel"),
              "expected": "SAME_EVENT"},
        "b": {"policy": "The vessel is cleaned after each batch. The "
                        "cleaning is logged by the shift lead.",
              "focus": ("The vessel is cleaned", "The cleaning is logged"),
              "expected": "RELATED_BUT_DIFFERENT"},
    },
    {
        "twin_id": "cf_payment",
        "mechanism": "required_vs_performed_occurrence",
        "a": {"policy": "Make the payment before the 5th. The payment "
                        "is confirmed by the finance desk after it is "
                        "made.",
              "focus": ("Make the payment", "The payment is confirmed"),
              "expected": "RELATED_BUT_DIFFERENT"},
        "b": {"policy": "Make the payment before the 5th. The payment "
                        "must be repeated if it is returned.",
              "focus": ("Make the payment", "The payment must be repeated"),
              "expected": "DIFFERENT_EVENT"},
    },
    {
        "twin_id": "cf_batch",
        "mechanism": "nominalization_reference",
        "a": {"policy": "Weigh each linen batch. The weighing is "
                        "witnessed by the shift lead.",
              "focus": ("Weigh each linen batch", "The weighing"),
              "expected": "SAME_EVENT"},
        "b": {"policy": "Weigh each linen batch. The weight of each "
                        "batch is recorded in the logbook.",
              "focus": ("Weigh each linen batch", "The weight"),
              "expected": "DIFFERENT_EVENT"},
    },
]

# ------------------------------------------------------------ rename map
RENAMES = {
    "batch": "cartridge", "inspection": "calibration", "weigh": "measure",
    "cleaning": "polishing", "log": "ledger", "vessel": "reactor",
    "clean": "polish", "cleaned": "polished", "inspect": "calibrate",
    "inspected": "calibrated", "weighing": "measuring",
}
RENAME_CASES = ["k_lighthouse", "k_icerink", "r_fountain", "r_ewaste",
                "n_chemistry", "n_maple"]


def _ren_text(s: str) -> str:
    """Case-preserving word-boundary rename."""
    def sub(m):
        w = m.group(0)
        dst = RENAMES[w.lower()]
        if w[0].isupper():
            dst = dst.capitalize()
        return dst
    return re.sub(r"\b(" + "|".join(RENAMES) + r")\b", sub, s)


def build_rename(c):
    """Semantic rename of a case (word-boundary, case-preserving)."""
    out = dict(c)
    out["policy"] = _ren_text(c["policy"])
    out["mentions"] = [(_ren_text(span), typ, cid_)
                       for span, typ, cid_ in c["mentions"]]
    out["normative_edges"] = [(f, t, list(acc), _ren_text(ev))
                              for f, t, acc, ev in c["normative_edges"]]
    out["tools"] = [{"name": t["name"], "description":
                     _ren_text(t["description"]), **TOOL_STUB}
                    for t in c["tools"]]
    out["case_id"] = c["case_id"] + "_ren"
    out["family"] = c["family"] + "_renamed"
    return out


# ------------------------------------------------------------- validation
def validate(cs):
    errs = []
    seen_ids = set()
    for c in cs:
        cid = c["case_id"]
        if cid in seen_ids:
            errs.append(f"{cid}: duplicate case_id")
        seen_ids.add(cid)
        pol = c["policy"]
        spans = [m[0] for m in c["mentions"]]
        # span verbatim + uniqueness
        for s in spans:
            if s not in pol:
                errs.append(f"{cid}: span not verbatim: {s!r}")
            if spans.count(s) > 1:
                errs.append(f"{cid}: duplicated span: {s!r}")
        cids = {m[2] for m in c["mentions"] if m[2]}
        for e in c["normative_edges"]:
            f, t, acc, ev = e[0], e[1], e[2], e[3]
            if f not in cids:
                errs.append(f"{cid}: edge from unknown cid {f}")
            if t not in cids:
                errs.append(f"{cid}: edge to unknown cid {t}")
            if f == t:
                errs.append(f"{cid}: self-edge {f}")
            if ev not in pol:
                errs.append(f"{cid}: evidence not verbatim: {ev!r}")
            if not acc or not all(isinstance(a, str) for a in acc):
                errs.append(f"{cid}: bad acceptable set {acc}")
        for p in c["related_pairs"] + c["ambiguous_pairs"]:
            if p[0] not in cids or p[1] not in cids:
                errs.append(f"{cid}: pair with unknown cid {p}")
            if p[0] == p[1]:
                errs.append(f"{cid}: self pair {p}")
        # policy ends with a period, reasonable length
        if len(pol) < 60 or len(pol) > 700:
            errs.append(f"{cid}: unusual policy length {len(pol)}")
        if not re.search(r"[.!?]$", pol.strip()):
            errs.append(f"{cid}: policy does not end with punctuation")
    return errs


def derive_pairs(c):
    """Derive mention-pair identity labels from gold structure."""
    ms = c["mentions"]
    edge_pairs = {(e[0], e[1]) for e in c["normative_edges"]} | \
                 {(e[1], e[0]) for e in c["normative_edges"]}
    rel = {(p[0], p[1]) for p in c["related_pairs"]} | \
          {(p[1], p[0]) for p in c["related_pairs"]}
    amb = {(p[0], p[1]) for p in c["ambiguous_pairs"]} | \
          {(p[1], p[0]) for p in c["ambiguous_pairs"]}
    pairs = []
    for i in range(len(ms)):
        for j in range(i + 1, len(ms)):
            a, b = ms[i], ms[j]
            if not a[2] or not b[2]:
                continue  # entity/junk mentions excluded from identity
            if (a[2], b[2]) in amb:
                lab = "AMBIGUOUS"
            elif a[2] == b[2]:
                lab = "SAME_EVENT"
            elif (a[2], b[2]) in rel or (a[2], b[2]) in edge_pairs:
                lab = "RELATED_BUT_DIFFERENT"
            else:
                lab = "DIFFERENT_EVENT"
            pairs.append({"a": a[0], "a_cid": a[2], "b": b[0],
                          "b_cid": b[2], "label": lab})
    return pairs


def main():
    errs = validate(CASES)
    if errs:
        print("VALIDATION FAILED:")
        for e in errs:
            print(" -", e)
        raise SystemExit(1)
    print(f"[f5] {len(CASES)} cases valid; "
          f"{sum(len(c['normative_edges']) for c in CASES)} gold edges; "
          f"{sum(len(c['mentions']) for c in CASES)} mentions; "
          f"{sum(len({m[2] for m in c['mentions'] if m[2]}) for c in CASES)} "
          f"canonical events")
    out = {"cases": CASES}
    blob = json.dumps(out, sort_keys=True, ensure_ascii=False)
    sha = hashlib.sha256(blob.encode()).hexdigest()
    (FROZEN / "f5_cases.json").write_text(json.dumps(out, indent=1),
                                          encoding="utf-8")
    pairs = {c["case_id"]: derive_pairs(c) for c in CASES}
    (FROZEN / "f5_pairs_gold.json").write_text(
        json.dumps(pairs, indent=1), encoding="utf-8")
    clusters = {c["case_id"]: {m[2]: [x[0] for x in c["mentions"]
                                      if x[2] == m[2]]
                               for m in c["mentions"] if m[2]}
                for c in CASES}
    (FROZEN / "f5_clusters_gold.json").write_text(
        json.dumps(clusters, indent=1), encoding="utf-8")
    graph = {c["case_id"]: [
        {"from": e[0], "to": e[1], "acceptable": e[2], "evidence": e[3]}
        for e in c["normative_edges"]] for c in CASES}
    (FROZEN / "f5_graph_gold.json").write_text(
        json.dumps(graph, indent=1), encoding="utf-8")
    # CF twins
    cf = {"twins": CF_TWINS}
    for t in CF_TWINS:
        for side in ("a", "b"):
            for span in t[side]["focus"]:
                if span not in t[side]["policy"]:
                    raise SystemExit(
                        f"CF {t['twin_id']}.{side}: focus span not "
                        f"verbatim: {span!r}")
    (FROZEN / "f5_cf_twins.json").write_text(
        json.dumps(cf, indent=1), encoding="utf-8")
    cf_blob = json.dumps(cf, sort_keys=True, ensure_ascii=False)
    cf_sha = hashlib.sha256(cf_blob.encode()).hexdigest()
    # rename suite
    ren_cases = [build_rename(c) for c in CASES
                 if c["case_id"] in RENAME_CASES]
    rerrs = validate(ren_cases)
    if rerrs:
        print("RENAME VALIDATION FAILED:")
        for e in rerrs:
            print(" -", e)
        raise SystemExit(1)
    (FROZEN / "f5_cases_renamed.json").write_text(
        json.dumps({"cases": ren_cases}, indent=1), encoding="utf-8")
    ren_blob = json.dumps({"cases": ren_cases}, sort_keys=True,
                          ensure_ascii=False)
    ren_sha = hashlib.sha256(ren_blob.encode()).hexdigest()
    manifest = {
        "name": "LEVEL_F5",
        "frozen_at": "2026-09-29",
        "sha256": sha,
        "cf_sha256": cf_sha,
        "renamed_sha256": ren_sha,
        "n_cases": len(CASES),
        "n_mentions": sum(len(c["mentions"]) for c in CASES),
        "n_canonical_events": sum(len({m[2] for m in c["mentions"]
                                       if m[2]}) for c in CASES),
        "n_gold_edges": sum(len(c["normative_edges"]) for c in CASES),
        "n_pairs": sum(len(v) for v in pairs.values()),
        "n_cf_twins": len(CF_TWINS),
        "n_renamed_cases": len(ren_cases),
        "pair_label_dist": {},
        "families": sorted({c["family"] for c in CASES}),
        "conventions": [
            "passive voice facet shares the action cid",
            "adjectival result state gets its own cid (RELATED)",
            "action / check-of-action / recording are distinct cids",
            "'again'/repetition = separate cid",
            "coordinated alternatives get no edge between them",
            "temporal NPs are ENTITY mentions, not events",
        ],
        "rule": "F5 is SEALED: no inference before this freeze; after "
                "the first F5 run no fixes measured on F5.",
    }
    from collections import Counter
    dist = Counter(p["label"] for v in pairs.values() for p in v)
    manifest["pair_label_dist"] = dict(dist)
    (FROZEN / "f5_manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"[f5] pair label dist: {dict(dist)}")
    print(f"[f5] cf twins: {len(CF_TWINS)}; renamed cases: "
          f"{len(ren_cases)} (validated)")
    print(f"[f5] manifest sha {sha[:16]}... written to {FROZEN}")
    return sha


if __name__ == "__main__":
    main()

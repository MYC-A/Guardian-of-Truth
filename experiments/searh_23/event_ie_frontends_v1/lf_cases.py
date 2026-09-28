"""Level F case definitions - READY IE FRONTENDS research.

New ontology (per protocol 2026-09-29):

  EVENT            imperative/passive/participial verbal mention of an action
  EVENT_REFERENCE  nominal or anaphoric mention pointing at an event
  STATE_OR_FACET   clause asserting a state/facet of an event (complete,
                   recorded, valid, found, approved...)
  ARTIFACT         document/record/report/log artefact
  CHECK            verifying action over a state or event
  ENTITY           participant (object, actor, time, quantity)
  UNKNOWN          cannot decide

Semantic mention links (NOT normative relations):

  SAME_EVENT       two EVENT mentions of the same occurrence
  REFERENCE_OF     EVENT_REFERENCE -> EVENT it refers to
  STATE_OF         STATE_OR_FACET -> event it is a state of
  ARTIFACT_ABOUT   ARTIFACT -> event it documents
  CHECKS           CHECK -> event/state it verifies

No case family copies a Level D/E/PL/relation_edges case verbatim; domains
are fresh relative to all 68 previously used domains. Cases are authored
for this phase and frozen before any inference.
"""
from __future__ import annotations


def tool(name: str, description: str) -> dict:
    return {"name": name, "description": description,
            "input": {"object_id": "string"}, "output": {"status": "string"}}


# type shorthand used in the case tables below
T_EVENT = "EVENT"
T_REF = "EVENT_REFERENCE"
T_STATE = "STATE_OR_FACET"
T_ART = "ARTIFACT"
T_CHECK = "CHECK"
T_ENTITY = "ENTITY"

CASES: list[dict] = [

    # --------------------------------------------------------------- 1
    dict(
        case_id="f_glass",
        domain="glassblowing studio",
        family="event_vs_artifact_vs_state",
        policy=(
            "Anneal glass ornament 3. Record the annealing in the batch log. "
            "Pack the ornament only after the annealing is finished and the "
            "log entry is stored. The annealing certificate is a document, "
            "not another annealing."
        ),
        tools=[
            tool("anneal_ornament", "Anneals one identified glass ornament."),
            tool("record_log", "Writes an entry into the batch log."),
            tool("pack_ornament", "Packs one identified glass ornament."),
        ],
        mentions=[
            ("m01", "Anneal glass ornament 3", T_EVENT, "E1"),
            ("m02", "glass ornament 3", T_ENTITY, None),
            ("m03", "Record the annealing", T_EVENT, "E2"),
            ("m04", "the annealing", T_REF, "E1"),
            ("m05", "the batch log", T_ART, None),
            ("m06", "Pack the ornament", T_EVENT, "E3"),
            ("m07", "the annealing is finished", T_STATE, "E1"),
            ("m08", "the log entry is stored", T_EVENT, "E2"),
            ("m09", "The annealing certificate", T_ART, None),
            ("m10", "another annealing", T_REF, "E1"),
        ],
        entities=[("X1", "object", ["m02"])],
        arguments=[("m01", "object", "X1")],
        events=[
            ("E1", "anneal", "OPERATION_EFFECT", "anneal_ornament"),
            ("E2", "record", "COMMUNICATION", "record_log"),
            ("E3", "pack", "OPERATION_EFFECT", "pack_ornament"),
        ],
        links=[
            ("REFERENCE_OF", "m04", "m01"),
            ("REFERENCE_OF", "m10", "m01"),
            ("STATE_OF", "m07", "E1"),
            ("SAME_EVENT", "m08", "m03"),
            ("ARTIFACT_ABOUT", "m05", "E2"),
            ("ARTIFACT_ABOUT", "m09", "E1"),
        ],
        edges=[
            ("E1", "E3", "PRECONDITION", ["PRECONDITION", "ORDER_BEFORE"],
             "Pack the ornament only after the annealing is finished"),
            ("E2", "E3", "PRECONDITION", ["PRECONDITION", "ORDER_BEFORE"],
             "Pack the ornament only after the annealing is finished and the log entry is stored"),
        ],
        notes="Artifact, reference and state all near the governed events; "
              "certificate must not become an event node.",
    ),

    # --------------------------------------------------------------- 2
    dict(
        case_id="f_turbine",
        domain="wind turbine maintenance",
        family="check_vs_state_dense",
        policy=(
            "Inspect the blades of turbine 12 on Monday. Log the inspection. "
            "Repair is permitted only if a crack is found. Repair the blades "
            "and verify that the repair passed the load test. The load test "
            "report is a document."
        ),
        tools=[
            tool("inspect_blades", "Inspects turbine blades."),
            tool("log_inspection", "Writes an inspection log entry."),
            tool("repair_blades", "Repairs turbine blades."),
            tool("verify_load_test", "Verifies a load test outcome."),
        ],
        mentions=[
            ("m01", "Inspect the blades of turbine 12", T_EVENT, "E1"),
            ("m02", "the blades", T_ENTITY, None),
            ("m03", "turbine 12", T_ENTITY, None),
            ("m04", "Monday", T_ENTITY, None),
            ("m05", "Log the inspection", T_EVENT, "E2"),
            ("m06", "the inspection", T_REF, "E1"),
            ("m07", "a crack is found", T_STATE, "E4"),
            ("m08", "Repair the blades", T_EVENT, "E3"),
            ("m09", "verify that the repair passed the load test", T_CHECK, "E6"),
            ("m11", "the load test", T_REF, "E5"),
            ("m10", "The load test report", T_ART, None),
        ],
        entities=[
            ("X1", "object", ["m02"]),
            ("X2", "object", ["m03"]),
            ("X3", "time", ["m04"]),
        ],
        arguments=[("m01", "object", "X1"), ("m01", "location", "X2"),
                   ("m01", "time", "X3"), ("m08", "object", "X1")],
        events=[
            ("E1", "inspect", "PRECONDITION_CHECK", "inspect_blades"),
            ("E2", "log", "COMMUNICATION", "log_inspection"),
            ("E3", "repair", "OPERATION_EFFECT", "repair_blades"),
            ("E4", "find", "OPERATION_EFFECT", None),
            ("E5", "test", "PRECONDITION_CHECK", None),
            ("E6", "verify", "PRECONDITION_CHECK", "verify_load_test"),
        ],
        links=[
            ("REFERENCE_OF", "m06", "m01"),
            ("REFERENCE_OF", "m11", "m09"),
            ("STATE_OF", "m07", "E4"),
            ("CHECKS", "m09", "E3"),
            ("ARTIFACT_ABOUT", "m10", "E5"),
        ],
        edges=[
            ("E4", "E3", "STATE_GATE", ["STATE_GATE", "PRECONDITION"],
             "Repair is permitted only if a crack is found"),
        ],
        notes="CHECK mention ('verify ... passed') must not merge with the "
              "load-test event; 'crack is found' is a state gating repair.",
    ),

    # --------------------------------------------------------------- 3
    dict(
        case_id="f_cocoa",
        domain="chocolate workshop",
        family="active_passive_nominalization",
        policy=(
            "Temper the cocoa mass. Molding may start only after the mass is "
            "tempered. The tempering record confirms the tempering. Store "
            "the molds after molding."
        ),
        tools=[
            tool("temper_mass", "Tempers cocoa mass."),
            tool("start_molding", "Starts chocolate molding."),
            tool("store_molds", "Stores chocolate molds."),
        ],
        mentions=[
            ("m01", "Temper the cocoa mass", T_EVENT, "E1"),
            ("m02", "the cocoa mass", T_ENTITY, None),
            ("m03", "Molding may start", T_EVENT, "E2"),
            ("m04", "the mass is tempered", T_EVENT, "E1"),
            ("m05", "The tempering record", T_ART, None),
            ("m06", "the tempering", T_REF, "E1"),
            ("m07", "Store the molds", T_EVENT, "E3"),
            ("m08", "molding", T_REF, "E2"),
        ],
        entities=[("X1", "object", ["m02"])],
        arguments=[("m01", "object", "X1")],
        events=[
            ("E1", "temper", "OPERATION_EFFECT", "temper_mass"),
            ("E2", "mold", "OPERATION_EFFECT", "start_molding"),
            ("E3", "store", "OPERATION_EFFECT", "store_molds"),
        ],
        links=[
            ("SAME_EVENT", "m04", "m01"),
            ("REFERENCE_OF", "m06", "m01"),
            ("REFERENCE_OF", "m08", "m03"),
            ("ARTIFACT_ABOUT", "m05", "E1"),
        ],
        edges=[
            ("E1", "E2", "PRECONDITION", ["PRECONDITION", "ORDER_BEFORE"],
             "Molding may start only after the mass is tempered"),
            ("E2", "E3", "ORDER_BEFORE", ["ORDER_BEFORE"],
             "Store the molds after molding"),
        ],
        notes="Passive 'is tempered' and nominal 'the tempering' both point "
              "at one occurrence; record is an artifact.",
    ),

    # --------------------------------------------------------------- 4
    dict(
        case_id="f_zoo",
        domain="zoo animal care",
        family="same_predicate_different_entity",
        policy=(
            "Feed the red pandas at 9. Feed the otters at 9. Weigh the red "
            "pandas only after feeding the red pandas. The feeding roster is "
            "a document."
        ),
        tools=[
            tool("feed_animal", "Feeds one identified animal."),
            tool("weigh_animal", "Weighs one identified animal."),
        ],
        mentions=[
            ("m01", "Feed the red pandas", T_EVENT, "E1"),
            ("m02", "the red pandas", T_ENTITY, None),
            ("m03", "9", T_ENTITY, None),
            ("m04", "Feed the otters", T_EVENT, "E2"),
            ("m05", "the otters", T_ENTITY, None),
            ("m06", "Weigh the red pandas", T_EVENT, "E3"),
            ("m07", "feeding the red pandas", T_EVENT, "E1"),
            ("m08", "The feeding roster", T_ART, None),
        ],
        entities=[
            ("X1", "object", ["m02"]),
            ("X2", "time", ["m03"]),
            ("X3", "object", ["m05"]),
        ],
        arguments=[("m01", "object", "X1"), ("m01", "time", "X2"),
                   ("m04", "object", "X3"), ("m04", "time", "X2"),
                   ("m06", "object", "X1")],
        events=[
            ("E1", "feed", "OPERATION_EFFECT", "feed_animal"),
            ("E2", "feed", "OPERATION_EFFECT", "feed_animal"),
            ("E3", "weigh", "OPERATION_EFFECT", "weigh_animal"),
        ],
        links=[
            ("SAME_EVENT", "m07", "m01"),
            ("ARTIFACT_ABOUT", "m08", "E1"),
        ],
        edges=[
            ("E1", "E3", "PRECONDITION", ["PRECONDITION", "ORDER_BEFORE"],
             "Weigh the red pandas only after feeding the red pandas"),
        ],
        notes="Feeding otters (E2) must not gate weighing pandas (E3); "
              "gerund 'feeding the red pandas' is a repeat mention of E1.",
    ),

    # --------------------------------------------------------------- 5
    dict(
        case_id="f_ski",
        domain="ski resort grooming",
        family="cross_sentence_anaphora",
        policy=(
            "Groom slope 2 before dawn. This grooming must be repeated "
            "before opening. Open the slope only after the grooming is "
            "complete and the grooming log is filed."
        ),
        tools=[
            tool("groom_slope", "Grooms one identified ski slope."),
            tool("open_slope", "Opens one identified ski slope."),
            tool("file_log", "Files a grooming log entry."),
        ],
        mentions=[
            ("m01", "Groom slope 2", T_EVENT, "E1"),
            ("m02", "slope 2", T_ENTITY, None),
            ("m03", "This grooming", T_REF, "E1"),
            ("m04", "Open the slope", T_EVENT, "E2"),
            ("m05", "the grooming is complete", T_STATE, "E1"),
            ("m06", "the grooming log is filed", T_EVENT, "E3"),
            ("m07", "the grooming log", T_ART, None),
        ],
        entities=[("X1", "object", ["m02"])],
        arguments=[("m01", "object", "X1")],
        events=[
            ("E1", "groom", "OPERATION_EFFECT", "groom_slope"),
            ("E2", "open", "OPERATION_EFFECT", "open_slope"),
            ("E3", "file", "COMMUNICATION", "file_log"),
        ],
        links=[
            ("REFERENCE_OF", "m03", "m01"),
            ("STATE_OF", "m05", "E1"),
            ("ARTIFACT_ABOUT", "m07", "E1"),
        ],
        edges=[
            ("E1", "E2", "PRECONDITION", ["PRECONDITION", "ORDER_BEFORE"],
             "Open the slope only after the grooming is complete"),
            ("E3", "E2", "PRECONDITION", ["PRECONDITION", "ORDER_BEFORE"],
             "Open the slope only after the grooming is complete and the grooming log is filed"),
        ],
        notes="'This grooming' refers across the sentence boundary; the "
              "grooming-log state belongs to the filing event E3, not E1.",
    ),

    # --------------------------------------------------------------- 6
    dict(
        case_id="f_bottling",
        domain="craft brewery bottling",
        family="negation_multiple_events_sentence",
        policy=(
            "Do not cap the bottles before the filler stops. Label each "
            "crate and pack each crate after capping. The capping tally is a "
            "document."
        ),
        tools=[
            tool("cap_bottles", "Caps bottled beer."),
            tool("label_crate", "Labels one identified crate."),
            tool("pack_crate", "Packs one identified crate."),
        ],
        mentions=[
            ("m01", "cap the bottles", T_EVENT, "E1"),
            ("m02", "the bottles", T_ENTITY, None),
            ("m03", "the filler stops", T_EVENT, "E4"),
            ("m04", "Label each crate", T_EVENT, "E2"),
            ("m05", "pack each crate", T_EVENT, "E3"),
            ("m06", "after capping", T_REF, "E1"),
            ("m07", "The capping tally", T_ART, None),
        ],
        entities=[("X1", "object", ["m02"])],
        arguments=[("m01", "object", "X1")],
        events=[
            ("E1", "cap", "OPERATION_EFFECT", "cap_bottles"),
            ("E2", "label", "OPERATION_EFFECT", "label_crate"),
            ("E3", "pack", "OPERATION_EFFECT", "pack_crate"),
            ("E4", "stop", "OPERATION_EFFECT", None),
        ],
        links=[
            ("REFERENCE_OF", "m06", "m01"),
            ("ARTIFACT_ABOUT", "m07", "E1"),
        ],
        edges=[
            ("E4", "E1", "PRECONDITION", ["PRECONDITION", "ORDER_BEFORE"],
             "Do not cap the bottles before the filler stops"),
            ("E1", "E2", "ORDER_BEFORE", ["ORDER_BEFORE"],
             "Label each crate and pack each crate after capping"),
            ("E1", "E3", "ORDER_BEFORE", ["ORDER_BEFORE"],
             "Label each crate and pack each crate after capping"),
        ],
        notes="Negated order ('do not ... before') still yields one "
              "precondition edge; two events in one coordinate sentence.",
    ),

    # --------------------------------------------------------------- 7
    dict(
        case_id="f_pest",
        domain="greenhouse pest control",
        family="modality_must_may",
        policy=(
            "Release the ladybirds before dawn. Spraying may proceed only "
            "after the greenhouse is vented. The spray log must record the "
            "spraying. Ladybird release is not spraying."
        ),
        tools=[
            tool("release_ladybirds", "Releases ladybirds into a greenhouse."),
            tool("vent_greenhouse", "Vents the greenhouse."),
            tool("spray_greenhouse", "Sprays pesticide in a greenhouse."),
            tool("record_spray_log", "Records a spray log entry."),
        ],
        mentions=[
            ("m01", "Release the ladybirds", T_EVENT, "E1"),
            ("m02", "the ladybirds", T_ENTITY, None),
            ("m03", "Spraying may proceed", T_EVENT, "E2"),
            ("m04", "the greenhouse is vented", T_EVENT, "E3"),
            ("m05", "The spray log", T_ART, None),
            ("m06", "record the spraying", T_EVENT, "E4"),
            ("m07", "the spraying", T_REF, "E2"),
            ("m08", "Ladybird release", T_REF, "E1"),
        ],
        entities=[("X1", "object", ["m02"])],
        arguments=[("m01", "object", "X1")],
        events=[
            ("E1", "release", "OPERATION_EFFECT", "release_ladybirds"),
            ("E2", "spray", "OPERATION_EFFECT", "spray_greenhouse"),
            ("E3", "vent", "OPERATION_EFFECT", "vent_greenhouse"),
            ("E4", "record", "COMMUNICATION", "record_spray_log"),
        ],
        links=[
            ("REFERENCE_OF", "m07", "m03"),
            ("REFERENCE_OF", "m08", "m01"),
            ("ARTIFACT_ABOUT", "m05", "E2"),
        ],
        edges=[
            ("E3", "E2", "PRECONDITION", ["PRECONDITION", "STATE_GATE"],
             "Spraying may proceed only after the greenhouse is vented"),
        ],
        notes="Final sentence explicitly separates two related nominal "
              "references; must/may modality present.",
    ),

    # --------------------------------------------------------------- 8
    dict(
        case_id="f_planet",
        domain="planetarium projection",
        family="state_validity_window",
        policy=(
            "Align the star projector. The alignment session is valid for 30 "
            "days. Present the evening show only while the alignment is "
            "valid. Renew the alignment after presenting."
        ),
        tools=[
            tool("align_projector", "Aligns the star projector."),
            tool("present_show", "Presents an identified show."),
            tool("renew_alignment", "Renews a projector alignment."),
        ],
        mentions=[
            ("m01", "Align the star projector", T_EVENT, "E1"),
            ("m02", "the star projector", T_ENTITY, None),
            ("m03", "The alignment session", T_REF, "E1"),
            ("m04", "30 days", T_ENTITY, None),
            ("m05", "Present the evening show", T_EVENT, "E2"),
            ("m06", "the alignment is valid", T_STATE, "E1"),
            ("m07", "Renew the alignment", T_EVENT, "E3"),
            ("m08", "the alignment", T_REF, "E1"),
        ],
        entities=[
            ("X1", "object", ["m02"]),
            ("X2", "duration", ["m04"]),
        ],
        arguments=[("m01", "object", "X1"), ("m03", "duration", "X2")],
        events=[
            ("E1", "align", "OPERATION_EFFECT", "align_projector"),
            ("E2", "present", "OPERATION_EFFECT", "present_show"),
            ("E3", "renew", "OPERATION_EFFECT", "renew_alignment"),
        ],
        links=[
            ("REFERENCE_OF", "m03", "m01"),
            ("REFERENCE_OF", "m08", "m01"),
            ("STATE_OF", "m06", "E1"),
        ],
        edges=[
            ("E1", "E2", "STATE_GATE", ["STATE_GATE", "PRECONDITION"],
             "Present the evening show only while the alignment is valid"),
            ("E2", "E3", "ORDER_AFTER", ["ORDER_AFTER", "RESPONSE"],
             "Renew the alignment after presenting"),
        ],
        notes="State ('is valid') differs from the aligning event; renewal "
              "is a distinct occurrence from the first alignment.",
    ),

    # --------------------------------------------------------------- 9
    dict(
        case_id="f_pit",
        domain="motorsport pit crew",
        family="same_predicate_entity_occurrence",
        policy=(
            "Change the front tyres during the first stop. Change the front "
            "tyres again during the second stop. Refuel the car only at the "
            "second stop. Each refuelling is a separate event from each tyre "
            "change."
        ),
        tools=[
            tool("change_tyres", "Changes car tyres."),
            tool("refuel_car", "Refuels the race car."),
        ],
        mentions=[
            ("m01", "Change the front tyres", T_EVENT, "E1"),
            ("m02", "the front tyres", T_ENTITY, None),
            ("m03", "the first stop", T_ENTITY, None),
            ("m04", "Change the front tyres again", T_EVENT, "E2"),
            ("m05", "the second stop", T_ENTITY, None),
            ("m06", "Refuel the car", T_EVENT, "E3"),
            ("m07", "the car", T_ENTITY, None),
            ("m08", "Each refuelling", T_REF, "E3"),
            ("m09", "each tyre change", T_REF, "E1"),
        ],
        entities=[
            ("X1", "object", ["m02"]),
            ("X2", "time", ["m03"]),
            ("X3", "time", ["m05"]),
            ("X4", "object", ["m07"]),
        ],
        arguments=[
            ("m01", "object", "X1"), ("m01", "time", "X2"),
            ("m04", "object", "X1"), ("m04", "time", "X3"),
            ("m06", "object", "X4"), ("m06", "time", "X3"),
        ],
        events=[
            ("E1", "change", "OPERATION_EFFECT", "change_tyres"),
            ("E2", "change", "OPERATION_EFFECT", "change_tyres"),
            ("E3", "refuel", "OPERATION_EFFECT", "refuel_car"),
        ],
        links=[
            ("REFERENCE_OF", "m08", "m06"),
            ("REFERENCE_OF", "m09", "m01"),
        ],
        edges=[],
        notes="Two tyre-change occurrences share predicate and entity but "
              "differ in time; refuelling at stop two must not merge with "
              "the second tyre change.",
    ),

    # --------------------------------------------------------------- 10
    dict(
        case_id="f_conserve",
        domain="museum painting conservation",
        family="wrong_endpoint_trap",
        policy=(
            "Conserve painting 9. Check the frame before installing the "
            "painting. The conservation report is filed after the painting "
            "is installed."
        ),
        tools=[
            tool("conserve_painting", "Conserves one identified painting."),
            tool("check_frame", "Checks a painting frame."),
            tool("install_painting", "Installs one identified painting."),
            tool("file_report", "Files a conservation report."),
        ],
        mentions=[
            ("m01", "Conserve painting 9", T_EVENT, "E1"),
            ("m02", "painting 9", T_ENTITY, None),
            ("m03", "Check the frame", T_EVENT, "E2"),
            ("m04", "the frame", T_ENTITY, None),
            ("m05", "installing the painting", T_EVENT, "E3"),
            ("m06", "The conservation report", T_ART, None),
            ("m08", "The conservation report is filed", T_EVENT, "E4"),
            ("m07", "the painting is installed", T_EVENT, "E3"),
        ],
        entities=[("X1", "object", ["m02"]), ("X2", "object", ["m04"])],
        arguments=[("m01", "object", "X1"), ("m03", "object", "X2")],
        events=[
            ("E1", "conserve", "OPERATION_EFFECT", "conserve_painting"),
            ("E2", "check", "PRECONDITION_CHECK", "check_frame"),
            ("E3", "install", "OPERATION_EFFECT", "install_painting"),
            ("E4", "file", "COMMUNICATION", "file_report"),
        ],
        links=[
            ("SAME_EVENT", "m05", "m07"),
            ("ARTIFACT_ABOUT", "m06", "E1"),
        ],
        edges=[
            ("E2", "E3", "PRECONDITION", ["PRECONDITION", "ORDER_BEFORE"],
             "Check the frame before installing the painting"),
            ("E3", "E4", "ORDER_AFTER", ["ORDER_AFTER", "RESPONSE"],
             "The conservation report is filed after the painting is installed"),
        ],
        notes="Conservation (E1) is thematically adjacent to every quote; "
              "the frame-check quote binds check->install, not conserve.",
    ),

    # --------------------------------------------------------------- 11
    dict(
        case_id="f_harvest",
        domain="vineyard harvest",
        family="dense_policy",
        policy=(
            "Sample the grapes of block 5 on Friday. Crush the grapes only "
            "after the sugar test is passed and the picking log is closed. "
            "Press the pomace after crushing. The press record confirms the "
            "pressing, not the crushing."
        ),
        tools=[
            tool("sample_grapes", "Samples grapes from one block."),
            tool("crush_grapes", "Crushes picked grapes."),
            tool("press_pomace", "Presses grape pomace."),
            tool("close_log", "Closes a picking log."),
        ],
        mentions=[
            ("m01", "Sample the grapes of block 5", T_EVENT, "E1"),
            ("m02", "the grapes", T_ENTITY, None),
            ("m03", "block 5", T_ENTITY, None),
            ("m04", "Friday", T_ENTITY, None),
            ("m05", "Crush the grapes", T_EVENT, "E2"),
            ("m06", "the sugar test is passed", T_STATE, "E5"),
            ("m07", "the picking log is closed", T_EVENT, "E4"),
            ("m08", "the picking log", T_ART, None),
            ("m09", "Press the pomace", T_EVENT, "E3"),
            ("m10", "the pomace", T_ENTITY, None),
            ("m11", "after crushing", T_REF, "E2"),
            ("m12", "The press record", T_ART, None),
            ("m13", "the pressing", T_REF, "E3"),
            ("m14", "the crushing", T_REF, "E2"),
        ],
        entities=[
            ("X1", "object", ["m02"]),
            ("X2", "location", ["m03"]),
            ("X3", "time", ["m04"]),
            ("X4", "object", ["m10"]),
        ],
        arguments=[
            ("m01", "object", "X1"), ("m01", "location", "X2"),
            ("m01", "time", "X3"), ("m05", "object", "X1"),
            ("m09", "object", "X4"),
        ],
        events=[
            ("E1", "sample", "PRECONDITION_CHECK", "sample_grapes"),
            ("E2", "crush", "OPERATION_EFFECT", "crush_grapes"),
            ("E3", "press", "OPERATION_EFFECT", "press_pomace"),
            ("E4", "close", "COMMUNICATION", "close_log"),
            ("E5", "test", "PRECONDITION_CHECK", "sample_grapes"),
        ],
        links=[
            ("STATE_OF", "m06", "E5"),
            ("ARTIFACT_ABOUT", "m08", "E4"),
            ("REFERENCE_OF", "m11", "m05"),
            ("ARTIFACT_ABOUT", "m12", "E3"),
            ("REFERENCE_OF", "m13", "m09"),
            ("REFERENCE_OF", "m14", "m05"),
        ],
        edges=[
            ("E5", "E2", "STATE_GATE", ["STATE_GATE", "PRECONDITION"],
             "Crush the grapes only after the sugar test is passed"),
            ("E4", "E2", "PRECONDITION", ["PRECONDITION", "ORDER_BEFORE"],
             "Crush the grapes only after the sugar test is passed and the picking log is closed"),
            ("E2", "E3", "ORDER_BEFORE", ["ORDER_BEFORE"],
             "Press the pomace after crushing"),
        ],
        notes="Dense: five events, two states, two artifacts, three "
              "references inside four sentences.",
    ),

    # --------------------------------------------------------------- 12
    dict(
        case_id="f_pool",
        domain="swimming pool treatment",
        family="state_vs_event_negative",
        policy=(
            "Disinfect the pool. Circulation must run for one hour. The "
            "disinfection level is acceptable only after circulation has "
            "run. Test the level before reopening. Acceptability is not "
            "disinfection."
        ),
        tools=[
            tool("disinfect_pool", "Disinfects the pool."),
            tool("run_circulation", "Runs pool circulation."),
            tool("test_level", "Tests the disinfection level."),
            tool("reopen_pool", "Reopens the pool."),
        ],
        mentions=[
            ("m01", "Disinfect the pool", T_EVENT, "E1"),
            ("m02", "the pool", T_ENTITY, None),
            ("m03", "Circulation must run", T_EVENT, "E2"),
            ("m04", "The disinfection level is acceptable", T_STATE, "E1"),
            ("m05", "circulation has run", T_EVENT, "E2"),
            ("m06", "Test the level", T_CHECK, "E4"),
            ("m07", "the level", T_ENTITY, None),
            ("m08", "reopening", T_EVENT, "E3"),
            ("m09", "Acceptability", T_REF, "E1"),
            ("m10", "disinfection", T_REF, "E1"),
        ],
        entities=[("X1", "object", ["m02"]), ("X2", "object", ["m07"])],
        arguments=[("m01", "object", "X1"), ("m06", "object", "X2")],
        events=[
            ("E1", "disinfect", "OPERATION_EFFECT", "disinfect_pool"),
            ("E2", "run", "OPERATION_EFFECT", "run_circulation"),
            ("E3", "reopen", "OPERATION_EFFECT", "reopen_pool"),
            ("E4", "test", "PRECONDITION_CHECK", "test_level"),
        ],
        links=[
            ("STATE_OF", "m04", "E1"),
            ("SAME_EVENT", "m05", "m03"),
            ("CHECKS", "m06", "E1"),
            ("REFERENCE_OF", "m09", "m04"),
            ("REFERENCE_OF", "m10", "m01"),
        ],
        edges=[
            ("E2", "E1", "PRECONDITION", ["PRECONDITION", "STATE_GATE"],
             "The disinfection level is acceptable only after circulation has run"),
        ],
        notes="'Acceptability' refers to the state, not to the disinfection "
              "event; test is a CHECK over the disinfection state.",
    ),

    # --------------------------------------------------------------- 13
    dict(
        case_id="f_hvac",
        domain="HVAC duct cleaning",
        family="reverse_direction_shared_predicate",
        policy=(
            "Replace the filter monthly without shutting down the unit. "
            "Replace the drive belt only after the unit is shut down. The "
            "belt replacement record is a document."
        ),
        tools=[
            tool("replace_filter", "Replaces the air filter."),
            tool("replace_belt", "Replaces the drive belt."),
            tool("shutdown_unit", "Shuts down the air unit."),
        ],
        mentions=[
            ("m01", "Replace the filter", T_EVENT, "E1"),
            ("m02", "the filter", T_ENTITY, None),
            ("m03", "shutting down the unit", T_EVENT, "E3"),
            ("m04", "Replace the drive belt", T_EVENT, "E2"),
            ("m05", "the drive belt", T_ENTITY, None),
            ("m06", "the unit is shut down", T_EVENT, "E3"),
            ("m07", "The belt replacement record", T_ART, None),
        ],
        entities=[("X1", "object", ["m02"]), ("X2", "object", ["m05"])],
        arguments=[("m01", "object", "X1"), ("m04", "object", "X2")],
        events=[
            ("E1", "replace", "OPERATION_EFFECT", "replace_filter"),
            ("E2", "replace", "OPERATION_EFFECT", "replace_belt"),
            ("E3", "shutdown", "OPERATION_EFFECT", "shutdown_unit"),
        ],
        links=[
            ("SAME_EVENT", "m03", "m06"),
            ("ARTIFACT_ABOUT", "m07", "E2"),
        ],
        edges=[
            ("E3", "E2", "PRECONDITION", ["PRECONDITION", "ORDER_BEFORE"],
             "Replace the drive belt only after the unit is shut down"),
        ],
        notes="Same predicate 'replace' twice with different objects; the "
              "filter replacement is explicitly NOT gated by shutdown.",
    ),

    # --------------------------------------------------------------- 14
    dict(
        case_id="f_shrimp",
        domain="shrimp aquaculture",
        family="check_vs_checked_state",
        policy=(
            "Measure the salinity each morning. The salinity reading must "
            "show 25 parts per thousand. Harvest the shrimp only after the "
            "salinity check passes. The harvest notice is a document."
        ),
        tools=[
            tool("measure_salinity", "Measures water salinity."),
            tool("harvest_shrimp", "Harvests shrimp from a pond."),
        ],
        mentions=[
            ("m01", "Measure the salinity", T_CHECK, "E1"),
            ("m02", "the salinity", T_ENTITY, None),
            ("m03", "each morning", T_ENTITY, None),
            ("m04", "The salinity reading", T_ART, None),
            ("m05", "25 parts per thousand", T_ENTITY, None),
            ("m06", "Harvest the shrimp", T_EVENT, "E2"),
            ("m07", "the salinity check passes", T_STATE, "E1"),
            ("m08", "the salinity check", T_REF, "E1"),
            ("m09", "The harvest notice", T_ART, None),
        ],
        entities=[
            ("X1", "object", ["m02"]),
            ("X2", "time", ["m03"]),
            ("X3", "value", ["m05"]),
        ],
        arguments=[("m01", "object", "X1"), ("m01", "time", "X2")],
        events=[
            ("E1", "measure", "PRECONDITION_CHECK", "measure_salinity"),
            ("E2", "harvest", "OPERATION_EFFECT", "harvest_shrimp"),
        ],
        links=[
            ("REFERENCE_OF", "m08", "m01"),
            ("STATE_OF", "m07", "E1"),
            ("ARTIFACT_ABOUT", "m04", "E1"),
            ("ARTIFACT_ABOUT", "m09", "E2"),
        ],
        edges=[
            ("E1", "E2", "PRECONDITION", ["PRECONDITION", "STATE_GATE"],
             "Harvest the shrimp only after the salinity check passes"),
        ],
        notes="CHECK (measure) vs its passing state; the reading artifact "
              "is not the check.",
    ),

    # --------------------------------------------------------------- 15
    dict(
        case_id="f_textile",
        domain="textile dyeing mill",
        family="artifact_about_reference_chain",
        policy=(
            "Dye the silk batch blue. Rinse the silk only after the dyeing "
            "is fixed. Keep the dyeing record for the audit. The audit is an "
            "inspection of the record, not of the dyeing."
        ),
        tools=[
            tool("dye_batch", "Dyes one identified textile batch."),
            tool("rinse_silk", "Rinses dyed silk."),
            tool("keep_record", "Archives a dyeing record."),
        ],
        mentions=[
            ("m01", "Dye the silk batch blue", T_EVENT, "E1"),
            ("m02", "the silk batch", T_ENTITY, None),
            ("m03", "blue", T_ENTITY, None),
            ("m04", "Rinse the silk", T_EVENT, "E2"),
            ("m05", "the dyeing is fixed", T_STATE, "E1"),
            ("m06", "the dyeing record", T_ART, None),
            ("m07", "the audit", T_CHECK, "E4"),
            ("m08", "the record", T_REF, "E3"),
            ("m09", "the dyeing", T_REF, "E1"),
        ],
        entities=[("X1", "object", ["m02"]), ("X2", "value", ["m03"])],
        arguments=[("m01", "object", "X1"), ("m01", "value", "X2"),
                   ("m04", "object", "X1")],
        events=[
            ("E1", "dye", "OPERATION_EFFECT", "dye_batch"),
            ("E2", "rinse", "OPERATION_EFFECT", "rinse_silk"),
            ("E3", "keep", "COMMUNICATION", "keep_record"),
            ("E4", "audit", "PRECONDITION_CHECK", None),
        ],
        links=[
            ("STATE_OF", "m05", "E1"),
            ("ARTIFACT_ABOUT", "m06", "E1"),
            ("CHECKS", "m07", "E3"),
            ("REFERENCE_OF", "m08", "m06"),
            ("REFERENCE_OF", "m09", "m01"),
        ],
        edges=[
            ("E1", "E2", "PRECONDITION", ["PRECONDITION", "STATE_GATE"],
             "Rinse the silk only after the dyeing is fixed"),
        ],
        notes="Reference chain: audit checks the record-keeping, which is "
              "about the dyeing; three-step chain must not collapse.",
    ),
]

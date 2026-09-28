"""Level F2/G sealed validation cases - READY IE FRONTENDS research.

Frozen together with Level F BEFORE any inference, but held sealed: these
cases must not be used for failure analysis, adapter tuning or mechanism
selection. They are only scored once, after the final pipeline is frozen.

Domains are fresh relative to every previously used domain and relative to
Level F. Constructions deliberately differ from Level F families.
"""
from __future__ import annotations

from lf_cases import tool, T_EVENT, T_REF, T_STATE, T_ART, T_CHECK, T_ENTITY

CASES: list[dict] = [

    dict(
        case_id="g_watertower",
        domain="water tower maintenance",
        family="sealed_inspection_certificate",
        policy=(
            "Drain tower 4. Clean the interior only after the tower is "
            "drained. The cleaning certificate confirms the cleaning. "
            "Refill the tower after the interior is clean."
        ),
        tools=[
            tool("drain_tower", "Drains one identified water tower."),
            tool("clean_interior", "Cleans a tower interior."),
            tool("refill_tower", "Refills one identified water tower."),
        ],
        mentions=[
            ("m01", "Drain tower 4", T_EVENT, "E1"),
            ("m02", "tower 4", T_ENTITY, None),
            ("m03", "Clean the interior", T_EVENT, "E2"),
            ("m04", "the tower is drained", T_EVENT, "E1"),
            ("m05", "The cleaning certificate", T_ART, None),
            ("m06", "the cleaning", T_REF, "E2"),
            ("m07", "Refill the tower", T_EVENT, "E3"),
            ("m08", "the interior is clean", T_STATE, "E2"),
        ],
        entities=[("X1", "object", ["m02"])],
        arguments=[("m01", "object", "X1"), ("m03", "location", "X1")],
        events=[
            ("E1", "drain", "OPERATION_EFFECT", "drain_tower"),
            ("E2", "clean", "OPERATION_EFFECT", "clean_interior"),
            ("E3", "refill", "OPERATION_EFFECT", "refill_tower"),
        ],
        links=[
            ("SAME_EVENT", "m04", "m01"),
            ("REFERENCE_OF", "m06", "m03"),
            ("STATE_OF", "m08", "E2"),
            ("ARTIFACT_ABOUT", "m05", "E2"),
        ],
        edges=[
            ("E1", "E2", "PRECONDITION", ["PRECONDITION", "ORDER_BEFORE"],
             "Clean the interior only after the tower is drained"),
            ("E2", "E3", "PRECONDITION", ["PRECONDITION", "STATE_GATE"],
             "Refill the tower after the interior is clean"),
        ],
        notes="Sealed: passive + certificate artifact + resulting state.",
    ),

    dict(
        case_id="g_curling",
        domain="curling rink ice",
        family="sealed_same_object_two_operations",
        policy=(
            "Scrape the ice of sheet 2. Pebble the ice after scraping, but "
            "only when the scrapes are dry. The pebbling log records the "
            "water temperature."
        ),
        tools=[
            tool("scrape_ice", "Scrapes curling ice."),
            tool("pebble_ice", "Pebbles curling ice."),
        ],
        mentions=[
            ("m01", "Scrape the ice", T_EVENT, "E1"),
            ("m02", "the ice", T_ENTITY, None),
            ("m03", "sheet 2", T_ENTITY, None),
            ("m04", "Pebble the ice", T_EVENT, "E2"),
            ("m05", "after scraping", T_REF, "E1"),
            ("m06", "the scrapes are dry", T_STATE, "E1"),
            ("m07", "The pebbling log", T_ART, None),
            ("m08", "the water temperature", T_ENTITY, None),
        ],
        entities=[
            ("X1", "object", ["m02"]),
            ("X2", "location", ["m03"]),
            ("X3", "object", ["m08"]),
        ],
        arguments=[("m01", "object", "X1"), ("m01", "location", "X2"),
                   ("m04", "object", "X1")],
        events=[
            ("E1", "scrape", "OPERATION_EFFECT", "scrape_ice"),
            ("E2", "pebble", "OPERATION_EFFECT", "pebble_ice"),
        ],
        links=[
            ("REFERENCE_OF", "m05", "m01"),
            ("STATE_OF", "m06", "E1"),
            ("ARTIFACT_ABOUT", "m07", "E2"),
        ],
        edges=[
            ("E1", "E2", "PRECONDITION", ["PRECONDITION", "ORDER_BEFORE"],
             "Pebble the ice after scraping"),
        ],
        notes="Sealed: one shared object under two operations, state of the "
              "scraping outcome gates pebbling; log artifact about a "
              "parameter, not about any event endpoint here.",
    ),

    dict(
        case_id="g_repeater",
        domain="ham radio repeater station",
        family="sealed_check_chain_artifact",
        policy=(
            "Measure the swr of antenna 2. The swr reading must be below "
            "two. Transmit only if the swr reading is below two. The "
            "transmit log is a document."
        ),
        tools=[
            tool("measure_swr", "Measures antenna SWR."),
            tool("transmit_message", "Transmits a radio message."),
        ],
        mentions=[
            ("m01", "Measure the swr of antenna 2", T_CHECK, "E1"),
            ("m02", "the swr", T_ENTITY, None),
            ("m03", "antenna 2", T_ENTITY, None),
            ("m04", "The swr reading", T_ART, None),
            ("m05", "two", T_ENTITY, None),
            ("m06", "Transmit", T_EVENT, "E2"),
            ("m07", "the swr reading is below two", T_STATE, "E1"),
            ("m08", "The transmit log", T_ART, None),
        ],
        entities=[
            ("X1", "object", ["m02"]),
            ("X2", "object", ["m03"]),
            ("X3", "value", ["m05"]),
        ],
        arguments=[("m01", "object", "X1"), ("m01", "location", "X2")],
        events=[
            ("E1", "measure", "PRECONDITION_CHECK", "measure_swr"),
            ("E2", "transmit", "OPERATION_EFFECT", "transmit_message"),
        ],
        links=[
            ("ARTIFACT_ABOUT", "m04", "E1"),
            ("STATE_OF", "m07", "E1"),
            ("ARTIFACT_ABOUT", "m08", "E2"),
        ],
        edges=[
            ("E1", "E2", "STATE_GATE", ["STATE_GATE", "PRECONDITION"],
             "Transmit only if the swr reading is below two"),
        ],
        notes="Sealed: bare-root imperative 'Transmit'; artifact shares its "
              "head noun with the measured quantity.",
    ),

    dict(
        case_id="g_yeast",
        domain="baking yeast laboratory",
        family="sealed_negation_exception",
        policy=(
            "Streak the plate. Incubate the plate at thirty degrees unless "
            "the culture is contaminated, in which case discard the plate. "
            "Discarding is not incubating. The incubation note is a "
            "document."
        ),
        tools=[
            tool("streak_plate", "Streaks a culture plate."),
            tool("incubate_plate", "Incubates a culture plate."),
            tool("discard_plate", "Discards a culture plate."),
        ],
        mentions=[
            ("m01", "Streak the plate", T_EVENT, "E1"),
            ("m02", "the plate", T_ENTITY, None),
            ("m03", "Incubate the plate", T_EVENT, "E2"),
            ("m04", "thirty degrees", T_ENTITY, None),
            ("m05", "the culture is contaminated", T_STATE, "E3"),
            ("m06", "discard the plate", T_EVENT, "E4"),
            ("m07", "Discarding", T_REF, "E4"),
            ("m08", "incubating", T_REF, "E2"),
            ("m09", "The incubation note", T_ART, None),
        ],
        entities=[("X1", "object", ["m02"]), ("X2", "value", ["m04"])],
        arguments=[("m01", "object", "X1"), ("m03", "object", "X1"),
                   ("m03", "value", "X2"), ("m06", "object", "X1")],
        events=[
            ("E1", "streak", "OPERATION_EFFECT", "streak_plate"),
            ("E2", "incubate", "OPERATION_EFFECT", "incubate_plate"),
            ("E3", "contaminate", "OPERATION_EFFECT", None),
            ("E4", "discard", "OPERATION_EFFECT", "discard_plate"),
        ],
        links=[
            ("STATE_OF", "m05", "E3"),
            ("REFERENCE_OF", "m07", "m06"),
            ("REFERENCE_OF", "m08", "m03"),
            ("ARTIFACT_ABOUT", "m09", "E2"),
        ],
        edges=[
            ("E3", "E4", "EXCEPTION", ["EXCEPTION"],
             "unless the culture is contaminated, in which case discard the plate"),
        ],
        notes="Sealed: unless-exception plus explicit 'X is not Y' "
              "separation of two gerund references.",
    ),

    dict(
        case_id="g_film",
        domain="archival film digitization",
        family="sealed_dense_reference_chain",
        policy=(
            "Inspect reel 7 for mold. Digitize the reel only after the "
            "inspection is logged and the mold check is negative. The "
            "digitization master is stored after digitizing. Storage of the "
            "master is not digitization."
        ),
        tools=[
            tool("inspect_reel", "Inspects a film reel."),
            tool("log_inspection", "Logs a film inspection."),
            tool("digitize_reel", "Digitizes a film reel."),
            tool("store_master", "Stores a digitization master."),
        ],
        mentions=[
            ("m01", "Inspect reel 7 for mold", T_CHECK, "E1"),
            ("m02", "reel 7", T_ENTITY, None),
            ("m03", "mold", T_ENTITY, None),
            ("m04", "Digitize the reel", T_EVENT, "E2"),
            ("m05", "the inspection is logged", T_STATE, "E4"),
            ("m06", "the mold check is negative", T_STATE, "E1"),
            ("m07", "The digitization master", T_ART, None),
            ("m08", "is stored", T_EVENT, "E3"),
            ("m09", "after digitizing", T_REF, "E2"),
            ("m10", "Storage of the master", T_REF, "E3"),
            ("m11", "digitization", T_REF, "E2"),
        ],
        entities=[("X1", "object", ["m02"]), ("X2", "object", ["m03"])],
        arguments=[("m01", "object", "X1"), ("m01", "object", "X2"),
                   ("m04", "object", "X1")],
        events=[
            ("E1", "inspect", "PRECONDITION_CHECK", "inspect_reel"),
            ("E2", "digitize", "OPERATION_EFFECT", "digitize_reel"),
            ("E3", "store", "OPERATION_EFFECT", "store_master"),
            ("E4", "log", "COMMUNICATION", "log_inspection"),
        ],
        links=[
            ("STATE_OF", "m05", "E4"),
            ("STATE_OF", "m06", "E1"),
            ("ARTIFACT_ABOUT", "m07", "E2"),
            ("REFERENCE_OF", "m09", "m04"),
            ("REFERENCE_OF", "m10", "m08"),
            ("REFERENCE_OF", "m11", "m04"),
        ],
        edges=[
            ("E1", "E2", "STATE_GATE", ["STATE_GATE", "PRECONDITION"],
             "Digitize the reel only after the inspection is logged and the mold check is negative"),
            ("E4", "E2", "PRECONDITION", ["PRECONDITION", "STATE_GATE"],
             "Digitize the reel only after the inspection is logged and the mold check is negative"),
            ("E2", "E3", "ORDER_AFTER", ["ORDER_AFTER", "RESPONSE"],
             "The digitization master is stored after digitizing"),
        ],
        notes="Sealed: dense four-event policy with two state gates, an "
              "artifact and a final explicit separation sentence.",
    ),
]

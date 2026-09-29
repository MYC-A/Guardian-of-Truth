"""Endpoint-grounded evidence certificate unit cases (Level F).

Small controlled policies with a candidate normative edge and a GOLD
certificate. These isolate the second key question of the phase: can the
evidence mechanism prove that a quote connects exactly endpoint A and
endpoint B, instead of a thematically plausible pair?

Gold certificate schema (per protocol):

  endpoint_a : {"span": ..., "ref_chain": [..] or []}   where in the
  endpoint_b :   SOURCE the endpoint is represented; ref_chain lists
                 intermediate reference spans when the endpoint is only
                 represented via reference (e.g. "This inspection").
  relation_trigger : {"span": ...} or null   the minimal text expressing
                 the relation BETWEEN the two endpoints.
  direction : "A_TO_B" | "B_TO_A" | null
  status    : SUPPORTED | UNSUPPORTED | AMBIGUOUS

UNSUPPORTED items still record where the endpoints live, so endpoint
anchoring can be scored separately from relation binding.
"""
from __future__ import annotations

ITEMS: list[dict] = [

    # ------------------------------------------------------------ positives
    dict(
        id="cf_pos_01",
        family="supported_plain",
        domain="koi pond care",
        policy="Bleach the filter housing. Stock the koi pond only after "
               "the housing is bleached.",
        edge={"a": "bleach the filter housing", "b": "stock the koi pond"},
        gold=dict(
            endpoint_a={"span": "Bleach the filter housing", "ref_chain": []},
            endpoint_b={"span": "the housing is bleached", "ref_chain": []},
            relation_trigger={"span": "only after"},
            direction="A_TO_B", status="SUPPORTED"),
        notes="Passive second mention of A; plain positive.",
    ),
    dict(
        id="cf_pos_02",
        family="supported_reference_chain",
        domain="climbing gym",
        policy="Inspect the harness. This inspection must precede every "
               "climb. The inspection tag is a document.",
        edge={"a": "inspect the harness", "b": "every climb"},
        gold=dict(
            endpoint_a={"span": "This inspection",
                        "ref_chain": ["This inspection", "Inspect the harness"]},
            endpoint_b={"span": "every climb", "ref_chain": []},
            relation_trigger={"span": "must precede"},
            direction="A_TO_B", status="SUPPORTED"),
        notes="Endpoint A only represented via reference; chain required.",
    ),
    dict(
        id="cf_pos_03",
        family="supported_cross_sentence",
        domain="river gauge station",
        policy="Calibrate the gauge weekly. This must be completed before "
               "each flood report is issued.",
        edge={"a": "calibrate the gauge", "b": "issue the flood report"},
        gold=dict(
            endpoint_a={"span": "This",
                        "ref_chain": ["This", "Calibrate the gauge"]},
            endpoint_b={"span": "each flood report is issued", "ref_chain": []},
            relation_trigger={"span": "must be completed before"},
            direction="A_TO_B", status="SUPPORTED"),
        notes="Pronoun reference across sentences.",
    ),
    dict(
        id="cf_pos_04",
        family="supported_state_gate",
        domain="jam kitchen",
        policy="Sterilize the jars. Label the batch only after the "
               "sterilization is complete.",
        edge={"a": "sterilize the jars", "b": "label the batch"},
        gold=dict(
            endpoint_a={"span": "the sterilization is complete",
                        "ref_chain": ["the sterilization is complete",
                                      "Sterilize the jars"]},
            endpoint_b={"span": "Label the batch", "ref_chain": []},
            relation_trigger={"span": "only after"},
            direction="A_TO_B", status="SUPPORTED"),
        notes="Gate is a completion state of A; still binds A to B.",
    ),
    dict(
        id="cf_pos_05",
        family="supported_unless_exception",
        domain="tram depot",
        policy="Sand the rails before every departure, unless the "
               "temperature is above thirty degrees.",
        edge={"a": "sand the rails", "b": "every departure"},
        gold=dict(
            endpoint_a={"span": "Sand the rails", "ref_chain": []},
            endpoint_b={"span": "every departure", "ref_chain": []},
            relation_trigger={"span": "before"},
            direction="A_TO_B", status="SUPPORTED"),
        notes="Exception clause present but core relation supported.",
    ),

    # ------------------------------------------------------ wrong endpoints
    dict(
        id="cf_neg_06",
        family="wrong_endpoint_closer_pair",
        domain="rope access team",
        policy="Inspect the hoist cable for frays. Replace the cable "
               "before lifting the boiler.",
        edge={"a": "inspect the hoist cable", "b": "replace the cable"},
        gold=dict(
            endpoint_a={"span": "Inspect the hoist cable for frays", "ref_chain": []},
            endpoint_b={"span": "Replace the cable", "ref_chain": []},
            relation_trigger=None,
            direction=None, status="UNSUPPORTED"),
        notes="Both endpoints exist; no quote connects them. The real edge "
              "is replace->lift.",
    ),
    dict(
        id="cf_neg_07",
        family="wrong_endpoint_thematic",
        domain="model workshop",
        policy="Train the new operator on the lathe. Test the lathe before "
               "the shift begins. Only a trained operator may drive the "
               "forklift.",
        edge={"a": "train the new operator", "b": "test the lathe"},
        gold=dict(
            endpoint_a={"span": "Train the new operator on the lathe", "ref_chain": []},
            endpoint_b={"span": "Test the lathe", "ref_chain": []},
            relation_trigger=None,
            direction=None, status="UNSUPPORTED"),
        notes="Thematic proximity must not create an edge; real edges are "
              "test->shift and train->drive.",
    ),
    dict(
        id="cf_pos_08",
        family="supported_distant_pair",
        domain="model workshop",
        policy="Train the new operator on the lathe. Test the lathe before "
               "the shift begins. Only a trained operator may drive the "
               "forklift.",
        edge={"a": "train the new operator", "b": "drive the forklift"},
        gold=dict(
            endpoint_a={"span": "a trained operator",
                        "ref_chain": ["a trained operator",
                                      "Train the new operator"]},
            endpoint_b={"span": "drive the forklift", "ref_chain": []},
            relation_trigger={"span": "Only"},
            direction="A_TO_B", status="SUPPORTED"),
        notes="Same policy as cf_neg_07; the third sentence does license "
              "train->drive via the participial modifier.",
    ),
    dict(
        id="cf_neg_09",
        family="argument_as_endpoint",
        domain="boiler room",
        policy="Inspect the gauge glass of boiler 2 before igniting "
               "boiler 2.",
        edge={"a": "the gauge glass", "b": "ignite boiler 2"},
        gold=dict(
            endpoint_a={"span": "the gauge glass", "ref_chain": []},
            endpoint_b={"span": "igniting boiler 2", "ref_chain": []},
            relation_trigger=None,
            direction=None, status="UNSUPPORTED"),
        notes="The gauge glass is an ARGUMENT of inspect, not an endpoint; "
              "the quote licenses inspect->ignite.",
    ),
    dict(
        id="cf_pos_10",
        family="supported_same_policy_argument",
        domain="boiler room",
        policy="Inspect the gauge glass of boiler 2 before igniting "
               "boiler 2.",
        edge={"a": "inspect the gauge glass", "b": "ignite boiler 2"},
        gold=dict(
            endpoint_a={"span": "Inspect the gauge glass", "ref_chain": []},
            endpoint_b={"span": "igniting boiler 2", "ref_chain": []},
            relation_trigger={"span": "before"},
            direction="A_TO_B", status="SUPPORTED"),
        notes="Companion positive to cf_neg_09 on the same policy.",
    ),

    # --------------------------------------------------- no asserted relation
    dict(
        id="cf_neg_11",
        family="both_endpoints_no_relation",
        domain="grain elevator",
        policy="Weigh the grain and dry the grain. The silo is cleaned "
               "weekly.",
        edge={"a": "weigh the grain", "b": "dry the grain"},
        gold=dict(
            endpoint_a={"span": "Weigh the grain", "ref_chain": []},
            endpoint_b={"span": "dry the grain", "ref_chain": []},
            relation_trigger=None,
            direction=None, status="UNSUPPORTED"),
        notes="Both endpoints in one sentence, coordination only; no "
              "ordering or gating asserted.",
    ),
    dict(
        id="cf_neg_12",
        family="descriptive_not_normative",
        domain="orchid nursery",
        policy="Mist the orchids in the morning. The misting usually "
               "precedes the watering round, which is performed by the "
               "day crew.",
        edge={"a": "mist the orchids", "b": "the watering round"},
        gold=dict(
            endpoint_a={"span": "Mist the orchids", "ref_chain": []},
            endpoint_b={"span": "the watering round", "ref_chain": []},
            relation_trigger=None,
            direction=None, status="UNSUPPORTED"),
        notes="'usually precedes' is descriptive, not a normative gate; "
              "asked edge stays unsupported for Guardian licensing.",
    ),

    # ------------------------------------------------------ reverse direction
    dict(
        id="cf_neg_13",
        family="reverse_direction",
        domain="letterpress studio",
        policy="Log the weight before shipping the parcel.",
        edge={"a": "ship the parcel", "b": "log the weight"},
        gold=dict(
            endpoint_a={"span": "shipping the parcel", "ref_chain": []},
            endpoint_b={"span": "Log the weight", "ref_chain": []},
            relation_trigger={"span": "before"},
            direction="B_TO_A", status="SUPPORTED"),
        notes="Relation exists but runs B->A; a certificate answering "
              "A_TO_B is a direction error.",
    ),
    dict(
        id="cf_neg_14",
        family="reverse_direction_state",
        domain="anodizing line",
        policy="The bath temperature must be logged before each rack is "
               "lowered.",
        edge={"a": "lower a rack", "b": "log the bath temperature"},
        gold=dict(
            endpoint_a={"span": "each rack is lowered", "ref_chain": []},
            endpoint_b={"span": "The bath temperature must be logged", "ref_chain": []},
            relation_trigger={"span": "before"},
            direction="B_TO_A", status="SUPPORTED"),
        notes="Passive endpoints; direction is log->lower.",
    ),

    # ------------------------------------------------ state vs event endpoint
    dict(
        id="cf_neg_15",
        family="state_gate_not_event_gate",
        domain="ferry slipway",
        policy="Fuel the ferry. The fuel gauge reading must exceed half. "
               "Sail the ferry only after the gauge reading exceeds half.",
        edge={"a": "fuel the ferry", "b": "sail the ferry"},
        gold=dict(
            endpoint_a={"span": "Fuel the ferry", "ref_chain": []},
            endpoint_b={"span": "Sail the ferry", "ref_chain": []},
            relation_trigger=None,
            direction=None, status="UNSUPPORTED"),
        notes="The gate is the STATE of the gauge, not the fueling event; "
              "no quote binds fuel->sail.",
    ),
    dict(
        id="cf_pos_16",
        family="supported_state_endpoint",
        domain="ferry slipway",
        policy="Fuel the ferry. The fuel gauge reading must exceed half. "
               "Sail the ferry only after the gauge reading exceeds half.",
        edge={"a": "the gauge reading exceeds half", "b": "sail the ferry"},
        gold=dict(
            endpoint_a={"span": "the gauge reading exceeds half", "ref_chain": []},
            endpoint_b={"span": "Sail the ferry", "ref_chain": []},
            relation_trigger={"span": "only after"},
            direction="A_TO_B", status="SUPPORTED"),
        notes="Companion positive: the state is the licensed endpoint.",
    ),

    # ------------------------------------------------ artifact vs event
    dict(
        id="cf_neg_17",
        family="artifact_not_endpoint",
        domain="x-ray screening lab",
        policy="Screen the parcel. File the screening certificate. Release "
               "the parcel only after the certificate is filed.",
        edge={"a": "screen the parcel", "b": "release the parcel"},
        gold=dict(
            endpoint_a={"span": "Screen the parcel", "ref_chain": []},
            endpoint_b={"span": "Release the parcel", "ref_chain": []},
            relation_trigger=None,
            direction=None, status="UNSUPPORTED"),
        notes="screen->release is only mediated by filing the certificate; "
              "the quote licenses file->release.",
    ),
    dict(
        id="cf_pos_18",
        family="supported_filing_event",
        domain="x-ray screening lab",
        policy="Screen the parcel. File the screening certificate. Release "
               "the parcel only after the certificate is filed.",
        edge={"a": "file the screening certificate", "b": "release the parcel"},
        gold=dict(
            endpoint_a={"span": "the certificate is filed",
                        "ref_chain": ["the certificate is filed",
                                      "File the screening certificate"]},
            endpoint_b={"span": "Release the parcel", "ref_chain": []},
            relation_trigger={"span": "only after"},
            direction="A_TO_B", status="SUPPORTED"),
        notes="Companion positive: filing event (passive mention) gates "
              "release.",
    ),

    # ------------------------------------------------ check vs checked state
    dict(
        id="cf_neg_19",
        family="check_vs_checked_state",
        domain="scent laboratory",
        policy="Verify the ph of the base mix. The verification confirms "
               "the ph reading. Bottle the batch only after the ph reading "
               "is verified.",
        edge={"a": "verify the ph", "b": "bottle the batch"},
        gold=dict(
            endpoint_a={"span": "Verify the ph of the base mix", "ref_chain": []},
            endpoint_b={"span": "Bottle the batch", "ref_chain": []},
            relation_trigger=None,
            direction=None, status="UNSUPPORTED"),
        notes="Careful item: the check and its passing state are closely "
              "related; the quote's endpoint is the verified reading "
              "(state), not the verify action. Judged UNSUPPORTED for the "
              "action endpoint under the strict certificate protocol.",
    ),
    dict(
        id="cf_pos_20",
        family="supported_verified_state",
        domain="scent laboratory",
        policy="Verify the ph of the base mix. The verification confirms "
               "the ph reading. Bottle the batch only after the ph reading "
               "is verified.",
        edge={"a": "the ph reading is verified", "b": "bottle the batch"},
        gold=dict(
            endpoint_a={"span": "the ph reading is verified",
                        "ref_chain": []},
            endpoint_b={"span": "Bottle the batch", "ref_chain": []},
            relation_trigger={"span": "only after"},
            direction="A_TO_B", status="SUPPORTED"),
        notes="Companion positive for the state endpoint.",
    ),

    # --------------------------------------------------------- ambiguous
    dict(
        id="cf_amb_21",
        family="or_group_ambiguity",
        domain="backstage crew",
        policy="Repair the projector or replace the projector before the "
               "rehearsal. Either repair satisfies the rehearsal "
               "requirement.",
        edge={"a": "repair the projector", "b": "the rehearsal"},
        gold=dict(
            endpoint_a={"span": "Repair the projector", "ref_chain": []},
            endpoint_b={"span": "the rehearsal", "ref_chain": []},
            relation_trigger={"span": "before"},
            direction="A_TO_B", status="SUPPORTED"),
        notes="OR-group member; individually supported, group logic handled "
              "elsewhere.",
    ),
    dict(
        id="cf_amb_22",
        family="member_to_member_ambiguity",
        domain="backstage crew",
        policy="Repair the projector or replace the projector before the "
               "rehearsal. Either repair satisfies the rehearsal "
               "requirement.",
        edge={"a": "repair the projector", "b": "replace the projector"},
        gold=dict(
            endpoint_a={"span": "Repair the projector", "ref_chain": []},
            endpoint_b={"span": "replace the projector", "ref_chain": []},
            relation_trigger=None,
            direction=None, status="UNSUPPORTED"),
        notes="OR-group members are alternatives, not mutually related.",
    ),
]

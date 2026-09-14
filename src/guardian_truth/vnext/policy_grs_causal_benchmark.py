"""GRS Stage A causal benchmark: 56 fresh cases, gold by construction.

Preregistration: docs/vnext/GRS_PREREG_GATES_V1.json (stage_a section).
Purpose: measure the COMPOSITION CEILING - given a correct grounded
inventory (oracle: facts with spans + modality/relation markers, neutral
IDs, no attachment information), can the frozen synthesizer compose the
correct behavioral ruleset in the frozen DSL?  This is a diagnostic
upper-bound experiment, NOT a deployable candidate; arm A0 (frozen H0) runs
on the same texts for paired statistics.

Composition (frozen): simple_controls 4, condition 4, exception 4,
condition_plus_exception 4, if_vs_only_if 4, modality 3, scope_togetherness
5, separate_clauses_modalities 4, per_clause_actors 4, temporal 4,
provenance_identity 2, negation 4, multi_axis 6, nl_prose_stress 3,
empty_gold_control 1 = 56.

Freshness (machine-checked): zero shared word 8-grams with every V4, V5,
PHV1 and PSB policy text; zero internal duplicates.

Gold by construction: each case carries its gold DSL ruleset (authored with
:atom placeholders, materialized to neutral inventory IDs), the oracle
inventory (facts + markers, IDs assigned by first appearance), the compiled
admissible program sets (same v3 program space as H0/PSB) and behavioral
worlds on the combined gold surface.  Machine checks: gold self-scores
correct; inventories well-formed (spans exact substrings, no role fields);
oracle evidence sufficiency (every gold modality/gate has a matching marker
on the primary reading; every marker is used); cohort-defining misbindings
are behaviorally observable; h0_representability by merge equivalence.

Conservative invariant: NO_VIOLATION is not PERMITTED.  One control case
(empty_gold_control) has an empty gold ruleset: the text regulates nothing,
so every world expects NO_VIOLATION.

Everything here is deterministic: no LLM, no network, no wall-clock.
"""
from dataclasses import dataclass

from .integrity import digest
from .policy_v3_benchmark import evaluate_v3_program  # noqa: F401 (continuity)
from .policy_v4_benchmark import build_v4_benchmark
from .policy_v5_benchmark import build_v5_benchmark
from .policy_phv1_holdout import build_phv1_holdout
from .policy_psb import composed_verdict
from .policy_psb_causal_benchmark import (
    _PERTURBATIONS, binding_detection_report, build_psb_causal_benchmark,
    h0_representable)
from .policy_grs import (
    GRSInvalid, compile_dsl, gold_dsl_refs, grs_score_prediction,
    grs_worlds, hallucination_attempts, materialize_gold_dsl, parse_dsl,
    validate_inventory)


@dataclass(frozen=True)
class PolicyGRSCase:
    case_id: str
    cohort: str
    style: str
    policy: str
    atom_catalog: tuple
    oracle_inventory: dict
    gold_dsl: str
    admissible_program_sets: tuple
    worlds: tuple
    axes: tuple
    h0_representable: bool

    def as_dict(self) -> dict:
        return {"case_id": self.case_id, "cohort": self.cohort,
                "style": self.style, "policy": self.policy,
                "atom_catalog": list(self.atom_catalog),
                "oracle_inventory": self.oracle_inventory,
                "gold_dsl": self.gold_dsl,
                "admissible_program_sets": [list(s) for s
                                            in self.admissible_program_sets],
                "worlds": [dict(w) for w in self.worlds],
                "axes": list(self.axes),
                "h0_representable": self.h0_representable}


COHORT_PLAN = {"simple_controls": 4, "condition": 4, "exception": 4,
               "condition_plus_exception": 4, "if_vs_only_if": 4,
               "modality": 3, "scope_togetherness": 5,
               "separate_clauses_modalities": 4, "per_clause_actors": 4,
               "temporal": 4, "provenance_identity": 2, "negation": 4,
               "multi_axis": 6, "nl_prose_stress": 3, "empty_gold_control": 1}

# entries: (key, text, gold_dsl, fact_spans, markers, inert, distractors)
# markers: (kind, value, span) with kind in {MODAL, RELATION}
ENTRIES: list[tuple] = []


def _register(cohort: str, cases: list) -> None:
    ENTRIES.append((cohort, "controlled", cases))


# --------------------------------------------------------- simple controls (4)

_register("simple_controls", [
    ("s01", "Volunteers must wear high-visibility vests inside the sorting hall.",
     "RULESET(RULE(REQUIRE, :action:wear_hiviz_vest))",
     {"action:wear_hiviz_vest": "wear high-visibility vests"},
     [("MODAL", "REQUIRE", "must")], [],
     ["action:wear_hard_hat", "state:sorting_hall_closed"]),
    ("s02", "Chemical concentrates may not be stored in the corridor lockers.",
     "RULESET(RULE(PROHIBIT, :action:store_concentrates_in_corridor_lockers))",
     {"action:store_concentrates_in_corridor_lockers":
      "stored in the corridor lockers"},
     [("MODAL", "PROHIBIT", "may not")], [],
     ["action:store_concentrates_in_lab_cabinet"]),
    ("s03", "Members of the astronomy club may borrow the portable telescope.",
     "RULESET(RULE(PERMIT, :action:borrow_the_portable_telescope))",
     {"action:borrow_the_portable_telescope": "borrow the portable telescope"},
     [("MODAL", "PERMIT", "may")], [],
     ["action:borrow_the_fixed_mount_camera"]),
    ("s04", "The fermentation room doors shall remain shut at all times.",
     "RULESET(RULE(REQUIRE, :state:fermentation_doors_shut))",
     {"state:fermentation_doors_shut": "remain shut"},
     [("MODAL", "REQUIRE", "shall")], [],
     ["state:fermentation_doors_open", "action:lock_fermentation_room"]),
])

# ---------------------------------------------------------------- condition (4)

_register("condition", [
    ("c01", "When the tide gauge reads double-high, the causeway crossing is forbidden.",
     "RULESET(RULE(PROHIBIT, :action:cross_the_causeway, WHEN(:state:tide_gauge_double_high)))",
     {"action:cross_the_causeway": "the causeway crossing",
      "state:tide_gauge_double_high": "the tide gauge reads double-high"},
     [("MODAL", "PROHIBIT", "forbidden"), ("RELATION", "IF", "When")], [],
     ["state:tide_gauge_low"]),
    ("c02", "Provided the pasteuriser has finished its cycle, workers may open the cheese vats.",
     "RULESET(RULE(PERMIT, :action:open_the_cheese_vats, WHEN(:state:pasteuriser_cycle_finished), ACTOR(:actor:worker)))",
     {"action:open_the_cheese_vats": "open the cheese vats",
      "state:pasteuriser_cycle_finished": "the pasteuriser has finished its cycle",
      "actor:worker": "workers"},
     [("MODAL", "PERMIT", "may"), ("RELATION", "IF", "Provided")], [],
     ["actor:manager"]),
    ("c03", "If the rhubarb beds are netted, pickers may gather stems.",
     "RULESET(RULE(PERMIT, :action:gather_stems, WHEN(:state:rhubarb_beds_netted), ACTOR(:actor:picker)))",
     {"action:gather_stems": "gather stems",
      "state:rhubarb_beds_netted": "the rhubarb beds are netted",
      "actor:picker": "pickers"},
     [("MODAL", "PERMIT", "may"), ("RELATION", "IF", "If")], [],
     ["action:pulverise_stems"]),
    ("c04", "Whenever the mangle is in motion, operators must keep their sleeves rolled.",
     "RULESET(RULE(REQUIRE, :action:keep_sleeves_rolled, WHEN(:state:mangle_in_motion), ACTOR(:actor:operator)))",
     {"action:keep_sleeves_rolled": "keep their sleeves rolled",
      "state:mangle_in_motion": "the mangle is in motion",
      "actor:operator": "operators"},
     [("MODAL", "REQUIRE", "must"), ("RELATION", "IF", "Whenever")], [],
     ["state:mangle_still"]),
])

# ---------------------------------------------------------------- exception (4)

_register("exception", [
    ("e01", "Visitors must not bring dogs onto the pickleball courts, except during scheduled training sessions.",
     "RULESET(RULE(PROHIBIT, :action:bring_dogs_onto_courts, EXCEPT(:state:scheduled_training_session)))",
     {"action:bring_dogs_onto_courts": "bring dogs onto the pickleball courts",
      "state:scheduled_training_session": "scheduled training sessions"},
     [("MODAL", "PROHIBIT", "must not"), ("RELATION", "UNLESS", "except")], [],
     ["action:bring_dogs_onto_the_lawn"]),
    ("e02", "The mead cellar must stay locked at all times, save when the house brewer needs access.",
     "RULESET(RULE(REQUIRE, :state:mead_cellar_locked, EXCEPT(:state:house_brewer_needs_access)))",
     {"state:mead_cellar_locked": "stay locked",
      "state:house_brewer_needs_access": "the house brewer needs access"},
     [("MODAL", "REQUIRE", "must"), ("RELATION", "UNLESS", "save when")], [],
     ["state:mead_cellar_stocked"]),
    ("e03", "The salt-glaze kiln may never be left unattended, except during the overnight anneal.",
     "RULESET(RULE(PROHIBIT, :state:kiln_left_unattended, EXCEPT(:state:overnight_anneal)))",
     {"state:kiln_left_unattended": "be left unattended",
      "state:overnight_anneal": "the overnight anneal"},
     [("MODAL", "PROHIBIT", "never"), ("RELATION", "UNLESS", "except")], [],
     ["state:kiln_door_open"]),
    ("e04", "Cadmium glazes are barred from the shared slab roller, save when the ceramics technician supervises.",
     "RULESET(RULE(PROHIBIT, :action:cadmium_glaze_on_slab_roller, EXCEPT(:state:ceramics_technician_supervises)))",
     {"action:cadmium_glaze_on_slab_roller": "Cadmium glazes",
      "state:ceramics_technician_supervises": "the ceramics technician supervises"},
     [("MODAL", "PROHIBIT", "barred"), ("RELATION", "UNLESS", "save when")], [],
     ["action:iron_oxide_glaze_on_slab_roller"]),
])

# ------------------------------------------------- condition + exception (4)

_register("condition_plus_exception", [
    ("ce01", "While the risograph is running, students must not enter the paper store, unless the print fellow signs a slip.",
     "RULESET(RULE(PROHIBIT, :action:enter_the_paper_store, WHEN(:state:risograph_running), EXCEPT(:state:print_fellow_signed_slip), ACTOR(:actor:student)))",
     {"action:enter_the_paper_store": "enter the paper store",
      "state:risograph_running": "the risograph is running",
      "state:print_fellow_signed_slip": "the print fellow signs a slip",
      "actor:student": "students"},
     [("MODAL", "PROHIBIT", "must not"), ("RELATION", "IF", "While"),
      ("RELATION", "UNLESS", "unless")], [],
     ["state:risograph_idle"]),
    ("ce02", "If the churn temperature drifts, visitors may not enter the butter room, except on booked tours.",
     "RULESET(RULE(PROHIBIT, :action:enter_the_butter_room, WHEN(:state:churn_temperature_drifts), EXCEPT(:state:booked_tour), ACTOR(:actor:visitor)))",
     {"action:enter_the_butter_room": "enter the butter room",
      "state:churn_temperature_drifts": "the churn temperature drifts",
      "state:booked_tour": "booked tours", "actor:visitor": "visitors"},
     [("MODAL", "PROHIBIT", "may not"), ("RELATION", "IF", "If"),
      ("RELATION", "UNLESS", "except")], [],
     ["state:churn_temperature_steady"]),
    ("ce03", "Whenever the loft hoist carries a load, climbing on the upper gallery is forbidden, save when the rigging marshal clears the climb.",
     "RULESET(RULE(PROHIBIT, :action:climb_the_upper_gallery, WHEN(:state:loft_hoist_carries_load), EXCEPT(:state:rigging_marshal_clears_climb)))",
     {"action:climb_the_upper_gallery": "climbing on the upper gallery",
      "state:loft_hoist_carries_load": "the loft hoist carries a load",
      "state:rigging_marshal_clears_climb": "the rigging marshal clears the climb"},
     [("MODAL", "PROHIBIT", "forbidden"), ("RELATION", "IF", "Whenever"),
      ("RELATION", "UNLESS", "save when")], [],
     ["action:climb_the_lower_gallery"]),
    ("ce04", "While the goat barn is quarantined, keepers must not ship the evening milk, unless the vet clears the herd.",
     "RULESET(RULE(PROHIBIT, :action:ship_the_evening_milk, WHEN(:state:goat_barn_quarantined), EXCEPT(:state:vet_clears_herd), ACTOR(:actor:keeper)))",
     {"action:ship_the_evening_milk": "ship the evening milk",
      "state:goat_barn_quarantined": "the goat barn is quarantined",
      "state:vet_clears_herd": "the vet clears the herd",
      "actor:keeper": "keepers"},
     [("MODAL", "PROHIBIT", "must not"), ("RELATION", "IF", "While"),
      ("RELATION", "UNLESS", "unless")], [],
     ["action:ship_the_morning_milk"]),
])

# ------------------------------------------------------------ IF vs ONLY_IF (4)

_register("if_vs_only_if", [
    ("io01", "Members may use the ice bath whenever the compression unit is serviced.",
     "RULESET(RULE(PERMIT, :action:use_the_ice_bath, WHEN(:state:compression_unit_serviced), ACTOR(:actor:member)))",
     {"action:use_the_ice_bath": "use the ice bath",
      "state:compression_unit_serviced": "the compression unit is serviced",
      "actor:member": "Members"},
     [("MODAL", "PERMIT", "may"), ("RELATION", "IF", "whenever")], [],
     ["state:compression_unit_faulty"]),
    ("io02", "Only when the compression unit is serviced may members use the ice bath.",
     "RULESET(RULE(PERMIT, :action:use_the_ice_bath, ONLY_WHEN(:state:compression_unit_serviced), ACTOR(:actor:member)))",
     {"action:use_the_ice_bath": "use the ice bath",
      "state:compression_unit_serviced": "the compression unit is serviced",
      "actor:member": "members"},
     [("MODAL", "PERMIT", "may"), ("RELATION", "ONLY_IF", "Only when")], [],
     ["state:compression_unit_faulty"]),
    ("io03", "Examinees may open the sealed envelope if the invigilator announces an audit.",
     "RULESET(RULE(PERMIT, :action:open_the_sealed_envelope, WHEN(:state:invigilator_announces_audit), ACTOR(:actor:examinee)))",
     {"action:open_the_sealed_envelope": "open the sealed envelope",
      "state:invigilator_announces_audit": "the invigilator announces an audit",
      "actor:examinee": "Examinees"},
     [("MODAL", "PERMIT", "may"), ("RELATION", "IF", "if")], [],
     ["action:open_the_spare_envelope"]),
    ("io04", "Examinees may open the sealed envelope only if the invigilator announces an audit.",
     "RULESET(RULE(PERMIT, :action:open_the_sealed_envelope, ONLY_WHEN(:state:invigilator_announces_audit), ACTOR(:actor:examinee)))",
     {"action:open_the_sealed_envelope": "open the sealed envelope",
      "state:invigilator_announces_audit": "the invigilator announces an audit",
      "actor:examinee": "Examinees"},
     [("MODAL", "PERMIT", "may"), ("RELATION", "ONLY_IF", "only if")], [],
     ["action:open_the_spare_envelope"]),
])

# ----------------------------------------------------------------- modality (3)

_register("modality", [
    ("m01", "Guests are free to wander the sculpture garden.",
     "RULESET(RULE(PERMIT, :action:wander_the_sculpture_garden, ACTOR(:actor:guest)))",
     {"action:wander_the_sculpture_garden": "wander the sculpture garden",
      "actor:guest": "Guests"},
     [("MODAL", "PERMIT", "are free to")], [],
     ["action:pick_the_sculptures"]),
    ("m02", "Feeding the koi from the bridge is not allowed.",
     "RULESET(RULE(PROHIBIT, :action:feed_the_koi_from_the_bridge))",
     {"action:feed_the_koi_from_the_bridge": "Feeding the koi from the bridge"},
     [("MODAL", "PROHIBIT", "not allowed")], [],
     ["action:feed_the_koi_from_the_bank"]),
    ("m03", "Every performer has to sign the stage register.",
     "RULESET(RULE(REQUIRE, :action:sign_the_stage_register, ACTOR(:actor:performer)))",
     {"action:sign_the_stage_register": "sign the stage register",
      "actor:performer": "performer"},
     [("MODAL", "REQUIRE", "has to")], [],
     ["action:sign_the_visitors_book"]),
])

# ---------------------------------------------------- scope / togetherness (5)

_register("scope_togetherness", [
    ("sc01", "Wax and resin must never be heated in the same pot.",
     "RULESET(RULE(PROHIBIT, TOGETHER(:action:wax_heated_in_pot, :action:resin_heated_in_pot)))",
     {"action:wax_heated_in_pot": "Wax", "action:resin_heated_in_pot": "resin"},
     [("MODAL", "PROHIBIT", "never")], [],
     ["action:heat_glue_in_pot"]),
    ("sc02", "You must log the dive and the ascent together on one slate.",
     "RULESET(RULE(REQUIRE, TOGETHER(:action:log_the_dive, :action:log_the_ascent)))",
     {"action:log_the_dive": "log the dive", "action:log_the_ascent": "the ascent"},
     [("MODAL", "REQUIRE", "must")], [],
     ["action:log_the_descent"]),
    ("sc03", "Firewood and kindling must never be stacked against the boiler wall.",
     "RULESET(RULE(PROHIBIT, SEPARATE(:action:firewood_against_boiler_wall, :action:kindling_against_boiler_wall)))",
     {"action:firewood_against_boiler_wall": "Firewood",
      "action:kindling_against_boiler_wall": "kindling"},
     [("MODAL", "PROHIBIT", "never")], [],
     ["action:peat_briquettes_against_boiler_wall"]),
    ("sc04", "Combining bleach and ammonia in the mop sink is forbidden.",
     "RULESET(RULE(PROHIBIT, TOGETHER(:action:bleach_in_mop_sink, :action:ammonia_in_mop_sink)))",
     {"action:bleach_in_mop_sink": "bleach", "action:ammonia_in_mop_sink": "ammonia"},
     [("MODAL", "PROHIBIT", "forbidden")], [],
     ["action:detergent_in_mop_sink"]),
    ("sc05", "Storing the seed bank duplicates and the voucher specimens in the same freezer is not permitted.",
     "RULESET(RULE(PROHIBIT, TOGETHER(:action:seed_duplicates_in_freezer, :action:voucher_specimens_in_freezer)))",
     {"action:seed_duplicates_in_freezer": "the seed bank duplicates",
      "action:voucher_specimens_in_freezer": "the voucher specimens"},
     [("MODAL", "PROHIBIT", "not permitted")], [],
     ["action:dna_samples_in_freezer"]),
])

# -------------------------------------------- separate clauses / modalities (4)

_register("separate_clauses_modalities", [
    ("sm01", "Volunteers may use the band saw after the safety briefing, and must clean the dust hood.",
     "RULESET(RULE(PERMIT, :action:use_the_band_saw, AFTER(:event:safety_briefing), ACTOR(:actor:volunteer)), RULE(REQUIRE, :action:clean_the_dust_hood, ACTOR(:actor:volunteer)))",
     {"action:use_the_band_saw": "use the band saw",
      "event:safety_briefing": "the safety briefing",
      "action:clean_the_dust_hood": "clean the dust hood",
      "actor:volunteer": "Volunteers"},
     [("MODAL", "PERMIT", "may"), ("MODAL", "REQUIRE", "must"),
      ("RELATION", "AFTER", "after")], [],
     ["action:use_the_plane_shaper"]),
    ("sm02", "Visitors may photograph the butterfly house, but flash units must stay off.",
     "RULESET(RULE(PERMIT, :action:photograph_the_butterfly_house, ACTOR(:actor:visitor)), RULE(REQUIRE, :state:flash_units_off))",
     {"action:photograph_the_butterfly_house": "photograph the butterfly house",
      "actor:visitor": "Visitors", "state:flash_units_off": "flash units"},
     [("MODAL", "PERMIT", "may"), ("MODAL", "REQUIRE", "must")], [],
     ["action:photograph_the_reptile_room"]),
    ("sm03", "When the kitchen runs a weekday service, the duty cook may requisition dry goods; when the fish van makes a delivery, the cook may not requisition fresh fish.",
     "RULESET(RULE(PERMIT, :action:requisition_dry_goods, WHEN(:state:kitchen_weekday_service), ACTOR(:actor:duty_cook)), RULE(PROHIBIT, :action:requisition_fresh_fish, WHEN(:state:fish_van_delivery), ACTOR(:actor:duty_cook)))",
     {"action:requisition_dry_goods": "requisition dry goods",
      "state:kitchen_weekday_service": "the kitchen runs a weekday service",
      "actor:duty_cook": "the duty cook",
      "action:requisition_fresh_fish": "requisition fresh fish",
      "state:fish_van_delivery": "the fish van makes a delivery"},
     [("MODAL", "PERMIT", "cook may requisition"), ("MODAL", "PROHIBIT", "may not"),
      ("RELATION", "IF", "When")], [],
     ["action:requisition_frozen_peas"]),
    ("sm04", "Apprentices may grind lenses at the dark bench, but polishing compounds are barred from the shared bench.",
     "RULESET(RULE(PERMIT, :action:grind_lenses_at_dark_bench, ACTOR(:actor:apprentice)), RULE(PROHIBIT, :action:polishing_compound_on_shared_bench))",
     {"action:grind_lenses_at_dark_bench": "grind lenses at the dark bench",
      "actor:apprentice": "Apprentices",
      "action:polishing_compound_on_shared_bench": "polishing compounds"},
     [("MODAL", "PERMIT", "may"), ("MODAL", "PROHIBIT", "barred")], [],
     ["action:grind_mirrors_at_dark_bench"]),
])

# ------------------------------------------------------- per-clause actors (4)

_register("per_clause_actors", [
    ("pa01", "Nurses may dispense the travel vaccines, and pharmacists must log every dispense.",
     "RULESET(RULE(PERMIT, :action:dispense_the_travel_vaccines, ACTOR(:actor:nurse)), RULE(REQUIRE, :action:log_every_dispense, ACTOR(:actor:pharmacist)))",
     {"action:dispense_the_travel_vaccines": "dispense the travel vaccines",
      "actor:nurse": "Nurses", "action:log_every_dispense": "log every dispense",
      "actor:pharmacist": "pharmacists"},
     [("MODAL", "PERMIT", "may"), ("MODAL", "REQUIRE", "must")], [],
     ["actor:receptionist"]),
    ("pa02", "Only the senior gardener may take cuttings from the mother fern; interns must water it each morning.",
     "RULESET(RULE(PERMIT, :action:take_cuttings_from_the_mother_fern, ONLY_ACTOR(:actor:senior_gardener)), RULE(REQUIRE, :action:water_the_mother_fern_each_morning, ACTOR(:actor:intern)))",
     {"action:take_cuttings_from_the_mother_fern":
      "take cuttings from the mother fern",
      "actor:senior_gardener": "the senior gardener",
      "action:water_the_mother_fern_each_morning": "water it each morning",
      "actor:intern": "interns"},
     [("MODAL", "PERMIT", "may"), ("MODAL", "REQUIRE", "must"),
      ("RELATION", "ONLY_IF", "Only")], [],
     ["actor:groundskeeper"]),
    ("pa03", "Couriers may leave parcels in the vestibule; residents must not collect parcels belonging to others.",
     "RULESET(RULE(PERMIT, :action:leave_parcels_in_the_vestibule, ACTOR(:actor:courier)), RULE(PROHIBIT, :action:collect_others_parcels, ACTOR(:actor:resident)))",
     {"action:leave_parcels_in_the_vestibule": "leave parcels in the vestibule",
      "actor:courier": "Couriers",
      "action:collect_others_parcels": "collect parcels belonging to others",
      "actor:resident": "residents"},
     [("MODAL", "PERMIT", "may"), ("MODAL", "PROHIBIT", "must not")], [],
     ["actor:concierge"]),
    ("pa04", "Deckhands may scrub the hull while daylight lasts; only the boatswain may signal the crane.",
     "RULESET(RULE(PERMIT, :action:scrub_the_hull, WHEN(:state:daylight_lasting), ACTOR(:actor:deckhand)), RULE(PERMIT, :action:signal_the_crane, ONLY_ACTOR(:actor:boatswain)))",
     {"action:scrub_the_hull": "scrub the hull",
      "state:daylight_lasting": "daylight lasts", "actor:deckhand": "Deckhands",
      "action:signal_the_crane": "signal the crane",
      "actor:boatswain": "the boatswain"},
     [("MODAL", "PERMIT", "Deckhands may"), ("RELATION", "IF", "while"),
      ("RELATION", "ONLY_IF", "only")], [],
     ["actor:galley_hand"]),
])

# ------------------------------------------------------------------ temporal (4)

_register("temporal", [
    ("tp01", "Once the proof has doubled, the loaf tins may go into the steam oven.",
     "RULESET(RULE(PERMIT, :action:loaf_tins_into_steam_oven, AFTER(:event:proof_has_doubled)))",
     {"action:loaf_tins_into_steam_oven": "the loaf tins",
      "event:proof_has_doubled": "the proof has doubled"},
     [("MODAL", "PERMIT", "may"), ("RELATION", "AFTER", "Once")], [],
     ["event:proof_collapsed"]),
    ("tp02", "The proofing cabinet must be sealed before the bakery opens.",
     "RULESET(RULE(REQUIRE, :action:seal_the_proofing_cabinet, BEFORE(:event:bakery_opens)))",
     {"action:seal_the_proofing_cabinet": "sealed",
      "event:bakery_opens": "the bakery opens"},
     [("MODAL", "REQUIRE", "must"), ("RELATION", "BEFORE", "before")], [],
     ["event:bakery_closes"]),
    ("tp03", "After the evening bell, visitors may not remain on the jetty.",
     "RULESET(RULE(PROHIBIT, :action:remain_on_the_jetty, AFTER(:event:evening_bell), ACTOR(:actor:visitor)))",
     {"action:remain_on_the_jetty": "remain on the jetty",
      "event:evening_bell": "the evening bell", "actor:visitor": "visitors"},
     [("MODAL", "PROHIBIT", "may not"), ("RELATION", "AFTER", "After")], [],
     ["event:morning_bell"]),
    ("tp04", "Once the biopsy results are filed, the records clerk may release the case notes.",
     "RULESET(RULE(PERMIT, :action:release_the_case_notes, AFTER(:event:biopsy_results_filed), ACTOR(:actor:records_clerk)))",
     {"action:release_the_case_notes": "release the case notes",
      "event:biopsy_results_filed": "the biopsy results are filed",
      "actor:records_clerk": "the records clerk"},
     [("MODAL", "PERMIT", "may"), ("RELATION", "AFTER", "Once")], [],
     ["event:biopsy_results_pending"]),
])

# --------------------------------------------------- provenance / identity (2)

_register("provenance_identity", [
    ("pi01", "Reimbursements must be backed by tool results only.",
     "RULESET(RULE(REQUIRE, :action:issue_reimbursement, PROVENANCE(:evidence:tool_result)))",
     {"action:issue_reimbursement": "Reimbursements",
      "evidence:tool_result": "tool results"},
     [("MODAL", "REQUIRE", "must"), ("RELATION", "ONLY_IF", "only")], [],
     ["evidence:verbal_claim"]),
    ("pi02", "Locker keys may be held only under the holder's own identity.",
     "RULESET(RULE(PERMIT, :action:hold_locker_key, IDENTITY(:identity:own_name)))",
     {"action:hold_locker_key": "held",
      "identity:own_name": "the holder's own identity"},
     [("MODAL", "PERMIT", "may"), ("RELATION", "ONLY_IF", "only")], [],
     ["identity:guest_pass"]),
])

# ------------------------------------------------------------------ negation (4)

_register("negation", [
    ("n01", "Provided the silo gauge does not read empty, workers may run the grain lift.",
     "RULESET(RULE(PERMIT, :action:run_the_grain_lift, WHEN(NOT(:state:silo_gauge_empty)), ACTOR(:actor:worker)))",
     {"action:run_the_grain_lift": "run the grain lift",
      "state:silo_gauge_empty": "the silo gauge does not read empty",
      "actor:worker": "workers"},
     [("MODAL", "PERMIT", "may"), ("RELATION", "IF", "Provided")], [],
     ["state:silo_gauge_full"]),
    ("n02", "If the annealing oven is not up to temperature, do not charge the crucible.",
     "RULESET(RULE(PROHIBIT, :action:charge_the_crucible, WHEN(NOT(:state:annealing_oven_up_to_temperature))))",
     {"action:charge_the_crucible": "charge the crucible",
      "state:annealing_oven_up_to_temperature":
      "the annealing oven is not up to temperature"},
     [("MODAL", "PROHIBIT", "do not"), ("RELATION", "IF", "If")], [],
     ["state:annealing_oven_cooling"]),
    ("n03", "When not on the duty roster, members may not borrow the workshop keys.",
     "RULESET(RULE(PROHIBIT, :action:borrow_the_workshop_keys, WHEN(NOT(:state:on_duty_roster)), ACTOR(:actor:member)))",
     {"action:borrow_the_workshop_keys": "borrow the workshop keys",
      "state:on_duty_roster": "not on the duty roster",
      "actor:member": "members"},
     [("MODAL", "PROHIBIT", "may not"), ("RELATION", "IF", "When")], [],
     ["state:on_standby_list"]),
    ("n04", "The snow gate may stay open only while the piste is not flagged red.",
     "RULESET(RULE(PERMIT, :state:snow_gate_open, ONLY_WHEN(NOT(:state:piste_flagged_red))))",
     {"state:snow_gate_open": "stay open",
      "state:piste_flagged_red": "not flagged red"},
     [("MODAL", "PERMIT", "may"), ("RELATION", "ONLY_IF", "only while")], [],
     ["state:piste_flagged_black"]),
])

# ---------------------------------------------------------------- multi-axis (6)

_register("multi_axis", [
    ("x01", "While the visiting surgeon is scrubbed, porters must not wheel the sterile trolley through the west corridor, except when the charge nurse escorts it.",
     "RULESET(RULE(PROHIBIT, :action:wheel_trolley_through_west_corridor, WHEN(:state:visiting_surgeon_scrubbed), EXCEPT(:state:charge_nurse_escorts), ACTOR(:actor:porter)))",
     {"action:wheel_trolley_through_west_corridor":
      "wheel the sterile trolley through the west corridor",
      "state:visiting_surgeon_scrubbed": "the visiting surgeon is scrubbed",
      "state:charge_nurse_escorts": "the charge nurse escorts it",
      "actor:porter": "porters"},
     [("MODAL", "PROHIBIT", "must not"), ("RELATION", "IF", "While"),
      ("RELATION", "UNLESS", "except when")], [],
     ["action:wheel_trolley_through_east_corridor"]),
    ("x02", "After the hive scale has been tared, beekeepers may open the brood box provided the smoker is lit.",
     "RULESET(RULE(PERMIT, :action:open_the_brood_box, AFTER(:event:hive_scale_tared), WHEN(:state:smoker_lit), ACTOR(:actor:beekeeper)))",
     {"action:open_the_brood_box": "open the brood box",
      "event:hive_scale_tared": "the hive scale has been tared",
      "state:smoker_lit": "the smoker is lit", "actor:beekeeper": "beekeepers"},
     [("MODAL", "PERMIT", "may"), ("RELATION", "AFTER", "After"),
      ("RELATION", "IF", "provided")], [],
     ["state:smoker_cold"]),
    ("x03", "While the observatory dome is open, visitors may use red torches, and the duty astronomer must log every white-light breach.",
     "RULESET(RULE(PERMIT, :action:use_red_torches, WHEN(:state:observatory_dome_open), ACTOR(:actor:visitor)), RULE(REQUIRE, :action:log_white_light_breaches, ACTOR(:actor:duty_astronomer)))",
     {"action:use_red_torches": "use red torches",
      "state:observatory_dome_open": "the observatory dome is open",
      "actor:visitor": "visitors",
      "action:log_white_light_breaches": "log every white-light breach",
      "actor:duty_astronomer": "the duty astronomer"},
     [("MODAL", "PERMIT", "may"), ("MODAL", "REQUIRE", "must"),
      ("RELATION", "IF", "While")], [],
     ["action:use_green_laser_pointers"]),
    ("x04", "When the varnish booth extractor is running, spirit-soaked rags and oily rags must never share the metal bin, save when the fire warden issues a bin permit.",
     "RULESET(RULE(PROHIBIT, TOGETHER(:action:spirit_rag_in_metal_bin, :action:oily_rag_in_metal_bin), WHEN(:state:varnish_booth_extractor_running), EXCEPT(:state:fire_warden_bin_permit)))",
     {"action:spirit_rag_in_metal_bin": "spirit-soaked rags",
      "action:oily_rag_in_metal_bin": "oily rags",
      "state:varnish_booth_extractor_running":
      "the varnish booth extractor is running",
      "state:fire_warden_bin_permit": "the fire warden issues a bin permit"},
     [("MODAL", "PROHIBIT", "never"), ("RELATION", "IF", "When"),
      ("RELATION", "UNLESS", "save when")], [],
     ["action:cotton_rag_in_metal_bin"]),
    ("x05", "Only when the boiler certificate is not expired may the auxiliary burner be lit.",
     "RULESET(RULE(PERMIT, :action:light_the_auxiliary_burner, ONLY_WHEN(NOT(:state:boiler_certificate_expired))))",
     {"action:light_the_auxiliary_burner": "the auxiliary burner",
      "state:boiler_certificate_expired": "the boiler certificate is not expired"},
     [("MODAL", "PERMIT", "may"), ("RELATION", "ONLY_IF", "Only when")], [],
     ["action:light_the_main_burner"]),
    ("x06", "Do not serve the raw-milk cheeses without the dairy manager's sign-off.",
     "RULESET(ONE_OF(RULE(PROHIBIT, :action:serve_the_raw_milk_cheeses, EXCEPT(:state:dairy_manager_signoff)), RULE(PROHIBIT, :action:serve_the_raw_milk_cheeses, WHEN(NOT(:state:dairy_manager_signoff)))))",
     {"action:serve_the_raw_milk_cheeses": "serve the raw-milk cheeses",
      "state:dairy_manager_signoff": "the dairy manager's sign-off"},
     [("MODAL", "PROHIBIT", "Do not"), ("RELATION", "UNLESS", "without")], [],
     ["action:serve_the_pasteurised_cheeses"]),
])

# ------------------------------------------------------------ NL prose stress (3)

_register("nl_prose_stress", [
    ("np01", "Because the cliff path crumbles after heavy rain, walkers must keep to the roped terrace until the warden has re-pegged the lower section, though the beach shortcut stays open throughout.",
     "RULESET(RULE(REQUIRE, :action:keep_to_the_roped_terrace, BEFORE(:event:warden_repegged_lower_section)))",
     {"action:keep_to_the_roped_terrace": "keep to the roped terrace",
      "event:warden_repegged_lower_section":
      "the warden has re-pegged the lower section"},
     [("MODAL", "REQUIRE", "must"), ("RELATION", "BEFORE", "until")],
     [("event:heavy_rain", "heavy rain"),
      ("state:beach_shortcut_open", "the beach shortcut stays open")],
     ["action:use_the_coastal_ladder"]),
    ("np02", "Although the loft is usually busy, juniors may fetch archive boxes on weekday mornings, provided the freight hatch is manned, but seniors must sign the ledger whenever they take the rare folios.",
     "RULESET(RULE(PERMIT, :action:fetch_archive_boxes, WHEN(AND(:state:weekday_morning, :state:freight_hatch_manned)), ACTOR(:actor:junior)), RULE(REQUIRE, :action:sign_the_ledger, WHEN(:action:take_rare_folios), ACTOR(:actor:senior)))",
     {"action:fetch_archive_boxes": "fetch archive boxes",
      "state:weekday_morning": "weekday mornings",
      "state:freight_hatch_manned": "the freight hatch is manned",
      "actor:junior": "juniors", "action:sign_the_ledger": "sign the ledger",
      "action:take_rare_folios": "take the rare folios",
      "actor:senior": "seniors"},
     [("MODAL", "PERMIT", "may"), ("MODAL", "REQUIRE", "must"),
      ("RELATION", "IF", "provided"), ("RELATION", "IF", "whenever")],
     [("state:loft_usually_busy", "the loft is usually busy")],
     ["action:fetch_map_drawers"]),
    ("np03", "Since the dye vats stain irreversibly, aprons must be worn at all times in the dye room, except in the drying alcove, where old clothes suffice.",
     "RULESET(RULE(REQUIRE, :state:aprons_worn, EXCEPT(:state:in_drying_alcove)))",
     {"state:aprons_worn": "aprons must be worn",
      "state:in_drying_alcove": "the drying alcove"},
     [("MODAL", "REQUIRE", "must"), ("RELATION", "UNLESS", "except")],
     [("state:dye_vats_stain_irreversibly", "the dye vats stain irreversibly"),
      ("action:old_clothes_suffice", "old clothes suffice")],
     ["state:gloves_worn"]),
])

# --------------------------------------------------------- empty-gold control (1)

_register("empty_gold_control", [
    ("z01", "The observatory gift shop sells star charts and postcards to visitors throughout the day, and the tea trolley parks by the main door every afternoon.",
     "RULESET()",
     {},
     [],
     [("action:sell_star_charts", "sells star charts"),
      ("action:sell_postcards", "postcards"),
      ("state:tea_trolley_parks_by_main_door",
       "the tea trolley parks by the main door")],
     ["action:enter_the_gift_shop", "action:buy_a_star_chart"]),
])


# --------------------------------------------------------------------- build

def _word_ngrams(text: str, n: int = 8) -> set:
    tokens = ["".join(ch for ch in word.lower() if ch.isalnum())
              for word in text.split()]
    tokens = [token for token in tokens if token]
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def development_text_ngrams() -> set:
    """8-gram novelty surface: every V4, V5, PHV1 and PSB policy text."""
    ngrams: set = set()
    for case in build_v4_benchmark(seed=260914):
        ngrams |= _word_ngrams(case.policy)
    for case in build_v5_benchmark(seed=260915):
        ngrams |= _word_ngrams(case.policy)
    for case in build_phv1_holdout():
        ngrams |= _word_ngrams(case.policy)
    for case in build_psb_causal_benchmark():
        ngrams |= _word_ngrams(case.policy)
    return ngrams


_REQUIRED_DETECTIONS = {
    "simple_controls": [], "condition": ["condition_exception_swap"],
    "exception": ["condition_exception_swap"],
    "condition_plus_exception": ["condition_exception_swap"],
    "if_vs_only_if": ["strength_flip"], "modality": ["modality_flip"],
    "scope_togetherness": [], "separate_clauses_modalities": ["modality_swap"],
    "per_clause_actors": ["actor_move"], "temporal": [],
    "provenance_identity": [], "negation": ["condition_exception_swap"],
    "multi_axis": ["condition_exception_swap"], "nl_prose_stress": [],
    "empty_gold_control": [],
}

_MODALITY_TO_MARKER = {"PERMIT": "PERMIT", "PROHIBIT": "PROHIBIT",
                       "REQUIRE": "REQUIRE"}
_GATE_TO_MARKER = {"WHEN": "IF", "ONLY_WHEN": "ONLY_IF", "IFF": "IFF",
                   "EXCEPT": "UNLESS", "BEFORE": "BEFORE", "AFTER": "AFTER",
                   # necessary-flavored gates compile to ONLY_IF and their
                   # surface evidence is an only/solely cue
                   "ONLY_ACTOR": "ONLY_IF", "IDENTITY": "ONLY_IF",
                   "PROVENANCE": "ONLY_IF"}


def _primary_rules(gold_dsl: str) -> list:
    """RULE nodes of the primary admissible reading (ONE_OF -> alternative 1
    plus the non-ONE_OF rules)."""
    ast = parse_dsl(gold_dsl)
    rules = []
    for rule in ast[1]:
        if rule[0] == "ONE_OF":
            rules.append(rule[1])
        else:
            rules.append(rule)
    return rules


def _axes_from_gold(gold_dsl: str) -> tuple:
    ast = parse_dsl(gold_dsl)
    axes: set = set()
    rules = []
    for rule in ast[1]:
        if rule[0] == "ONE_OF":
            rules.append(rule[1])
            axes.add("ambiguity")
        else:
            rules.append(rule)
    for rule in rules:
        for gate in rule[3]:
            op = gate[0]
            if op in ("WHEN", "ONLY_WHEN", "IFF"):
                axes.add("condition")
            elif op == "EXCEPT":
                axes.add("exception")
            elif op in ("BEFORE", "AFTER"):
                axes.add("temporal")
            elif op in ("ACTOR", "ONLY_ACTOR"):
                axes.add("actor")
            elif op == "IDENTITY":
                axes.add("identity")
            elif op == "PROVENANCE":
                axes.add("provenance")
            if op in ("WHEN", "ONLY_WHEN", "IFF", "EXCEPT", "BEFORE", "AFTER") \
                    and any(leaf[0] == "NOT" for leaf in gate[1][1]):
                axes.add("negation")
        if rule[2][0] == "TOGETHER":
            axes.add("together")
        elif rule[2][0] == "SEPARATE":
            axes.add("separate")
    if len(rules) > 1:
        axes.add("multiclause")
        if len({rule[1] for rule in rules}) > 1:
            axes.add("modality")
    return tuple(sorted(axes))


def _evidence_sufficiency(gold_dsl: str, inventory: dict, case_key: str) -> None:
    """Oracle consistency on the primary reading: every gold modality and
    relation gate has a matching marker; every marker is used."""
    rules = _primary_rules(gold_dsl)
    modalities = {rule[1] for rule in rules}
    gate_ops = {gate[0] for rule in rules for gate in rule[3]}
    needed_modal = {_MODALITY_TO_MARKER[m] for m in modalities}
    needed_relation = {_GATE_TO_MARKER[op] for op in gate_ops
                       if op in _GATE_TO_MARKER}
    have_modal, have_relation = set(), set()
    for marker in inventory["markers"]:
        if marker["kind"] == "MODAL_MARKER":
            have_modal.add(marker["value"])
        else:
            have_relation.add(marker["value"])
    if not needed_modal <= have_modal:
        raise ValueError(f"{case_key}: gold modality without marker: "
                         f"{needed_modal - have_modal}")
    if not needed_relation <= have_relation:
        raise ValueError(f"{case_key}: gold gate without marker: "
                         f"{needed_relation - have_relation}")
    if not have_modal <= needed_modal or not have_relation <= needed_relation:
        raise ValueError(f"{case_key}: orphan or contradicting markers: "
                         f"modal {have_modal - needed_modal}, "
                         f"relation {have_relation - needed_relation}")


def build_grs_cases(entries, dev_ngrams: set, cohort_plan: dict,
                    seen_texts: set | None = None,
                    seen_ngrams: set | None = None,
                    required_detections: dict | None = None) -> list[PolicyGRSCase]:
    """Shared gold-by-construction builder for GRS corpora (Stage A and the
    Stage B prospective corpus import this).  Machine checks: inventory
    well-formedness, gold self-score, discriminating worlds, oracle evidence
    sufficiency, cohort-defining perturbation detectability, 8-gram novelty
    vs the supplied development surface and internally/externally seen
    texts, unique span positions for neutral ID assignment."""
    seen_texts = set() if seen_texts is None else seen_texts
    seen_ngrams = set() if seen_ngrams is None else seen_ngrams
    detections = required_detections or _REQUIRED_DETECTIONS
    cases: list[PolicyGRSCase] = []
    for cohort, style, cases_entries in entries:
        for key, text, gold_dsl, fact_spans, markers, inert, distractors in cases_entries:
            refs = gold_dsl_refs(gold_dsl)
            if refs != set(fact_spans):
                raise ValueError(f"{cohort}::{key}: gold refs and spans differ: "
                                 f"{refs ^ set(fact_spans)}")
            all_facts = dict(fact_spans)
            for atom, span in inert:
                if atom in all_facts:
                    raise ValueError(f"{cohort}::{key}: inert atom {atom} "
                                     "collides with a gold ref")
                all_facts[atom] = span
            positions = []
            for atom, span in sorted(all_facts.items()):
                if text.count(span) != 1:
                    raise ValueError(f"{cohort}::{key}: span {span!r} for "
                                     f"{atom} is not unique in the text")
                positions.append((text.index(span), atom, span))
            if len({p[0] for p in positions}) != len(positions):
                raise ValueError(f"{cohort}::{key}: duplicate span positions")
            atom_to_id = {atom: f"F{index + 1}" for index, (_, atom, _)
                          in enumerate(sorted(positions))}
            marker_rows = []
            for index, (kind, value, span) in enumerate(sorted(
                    markers, key=lambda m: text.index(m[2]))):
                if text.count(span) != 1:
                    raise ValueError(f"{cohort}::{key}: marker span {span!r} "
                                     "is not unique in the text")
                prefix = "M" if kind == "MODAL" else "R"
                full_kind = ("MODAL_MARKER" if kind == "MODAL"
                             else "RELATION_MARKER")
                marker_rows.append({"id": f"{prefix}{index + 1}",
                                    "kind": full_kind, "value": value,
                                    "span": span})
            fact_rows = []
            for index, (_, atom, span) in enumerate(sorted(positions)):
                kind = atom.split(":", 1)[0]
                kind = {"evidence": "PROVENANCE"}.get(kind, kind).upper()
                fact_rows.append({"id": f"F{index + 1}", "kind": kind,
                                  "atom": atom, "span": span})
            inventory = {"facts": fact_rows, "markers": marker_rows}
            validate_inventory(inventory, text)
            materialized = materialize_gold_dsl(gold_dsl, atom_to_id)
            alternatives, dropped = compile_dsl(materialized, inventory)
            if dropped:
                raise ValueError(f"{cohort}::{key}: gold rules dropped: {dropped}")
            admissible_sets = tuple(tuple(programs) for programs in alternatives)
            worlds = grs_worlds(admissible_sets)
            correct, _per = grs_score_prediction(alternatives, worlds,
                                                 admissible_sets)
            if not correct:
                raise ValueError(f"gold does not self-score correct: "
                                 f"{cohort}::{key}")
            if admissible_sets[0]:
                acceptable = {composed_verdict(admissible_sets[0],
                                               frozenset(w["facts"]))
                              for w in worlds}
                if acceptable == {"NO_VIOLATION"}:
                    raise ValueError(f"no discriminating world: {cohort}::{key}")
            _evidence_sufficiency(materialized, inventory, f"{cohort}::{key}")
            detection = binding_detection_report(admissible_sets, worlds)
            for required in detections[cohort]:
                if detection[required]["n_perturbations"] \
                        and not detection[required]["detected"]:
                    raise ValueError(f"{required} not detectable: "
                                     f"{cohort}::{key}")
            ngrams = _word_ngrams(text)
            if ngrams & dev_ngrams:
                raise ValueError(f"8-gram overlap with development corpus: "
                                 f"{cohort}::{key}")
            if ngrams & seen_ngrams:
                raise ValueError(f"internal 8-gram duplication: {cohort}::{key}")
            if text in seen_texts:
                raise ValueError(f"internal text duplication: {cohort}::{key}")
            seen_texts.add(text)
            seen_ngrams |= ngrams
            catalog_atoms = set(all_facts) | set(distractors)
            catalog_atoms.add(f"distractor:{key}")
            case = PolicyGRSCase(
                case_id=f"{cohort}::{key}", cohort=cohort, style=style,
                policy=text, atom_catalog=tuple(sorted(catalog_atoms)),
                oracle_inventory=inventory, gold_dsl=materialized,
                admissible_program_sets=admissible_sets,
                worlds=tuple(worlds), axes=_axes_from_gold(materialized),
                h0_representable=h0_representable(admissible_sets, worlds))
            cases.append(case)
    observed = {}
    for case in cases:
        observed[case.cohort] = observed.get(case.cohort, 0) + 1
    if observed != cohort_plan:
        raise ValueError(f"cohort composition mismatch: {observed}")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("duplicate case ids")
    return sorted(cases, key=lambda case: case.case_id)


def build_grs_stage_a_benchmark() -> list[PolicyGRSCase]:
    """Build the frozen GRS Stage A corpus deterministically (56 cases) with
    every machine self-check from the preregistration."""
    return build_grs_cases(ENTRIES, development_text_ngrams(), COHORT_PLAN)




def benchmark_grs_stage_a_document(cases: list[PolicyGRSCase]) -> dict:
    rows = [case.as_dict() for case in cases]
    return {"schema_version": "guardian-vnext-policy-grs-stage-a-v1",
            "prereg": "docs/vnext/GRS_PREREG_GATES_V1.json",
            "frozen_before_predictions": True,
            "annotation_basis": "CONSTRUCTION_FROM_TEMPLATES_NOT_MODEL_LABELS",
            "cohorts": dict(COHORT_PLAN),
            "cases_sha256": digest(rows), "cases": rows}

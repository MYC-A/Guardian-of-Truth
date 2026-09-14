"""PSB causal benchmark: 44 fresh cases, gold by construction.

Preregistration: docs/vnext/PSB_PREREG_GATES_V1.json (causal_benchmark
section). Purpose: causally measure (a) the value of explicit typed
attachment binding (H1 vs frozen H0) and (b) the value of the frozen
positive-evidence permission gate (H2 vs H1) on binding-sensitive policy
texts. NOT a confirmatory holdout: this corpus is development evidence for
the candidate; the final prospective holdout (Stage B) is separate.

Composition (frozen): 12 relation/attachment, 8 exception-vs-condition,
8 multi-clause modality/actor binding, 8 permission-evidence controls,
8 multi-axis controls.

Freshness (machine-checked in build): zero shared word 8-grams with every
V4, V5 and PHV1 policy text; zero internal duplicate texts.

Gold by construction: each case carries its gold semantic GRAPH (nodes +
edges), compiled deterministically with compile_psb_graph (gate off) into
the admissible program set; behavioral worlds are generated on the combined
gold surface. Machine checks: gold self-scores correct; cohort-defining
misbindings (condition<->exception swap, strength flip, modality swap,
actor move, gate move, polarity flip, clause merge/split) change composed
verdicts on at least one frozen world; h0_representability is computed by
merge-equivalence (a single flat v3 program reproducing every composed
gold verdict), not by hand.

Conservative invariant: NO_VIOLATION is not PERMITTED. One control case
(harbour by-laws) has an empty gold program set: the text regulates
nothing, so every world expects NO_VIOLATION.

Everything here is deterministic: no LLM, no network, no wall-clock.
"""
from dataclasses import dataclass

from .integrity import digest
from .policy_v3_benchmark import evaluate_v3_program
from .policy_v4_benchmark import build_v4_benchmark
from .policy_v5_benchmark import build_v5_benchmark
from .policy_phv1_holdout import build_phv1_holdout
from .policy_psb import (compile_psb_graph, composed_verdict,
                         generate_worlds_for_sets, score_program_set)


@dataclass(frozen=True)
class PolicyPSBCase:
    case_id: str
    cohort: str
    family: str
    style: str
    policy: str
    atom_catalog: tuple
    gold_graph: dict
    admissible_program_sets: tuple
    worlds: tuple
    axes: tuple
    h0_representable: bool

    def as_dict(self) -> dict:
        return {"case_id": self.case_id, "cohort": self.cohort,
                "family": self.family, "style": self.style,
                "policy": self.policy, "atom_catalog": list(self.atom_catalog),
                "gold_graph": self.gold_graph,
                "admissible_program_sets": [list(s) for s in self.admissible_program_sets],
                "worlds": [dict(w) for w in self.worlds],
                "axes": list(self.axes),
                "h0_representable": self.h0_representable}


# ------------------------------------------------------------- graph helpers

def N(node_id: str, node_type: str, **fields) -> dict:
    return {"id": node_id, "type": node_type, **fields}


def E(edge_type: str, src: str, dst: str) -> dict:
    return {"type": edge_type, "from": src, "to": dst}


def _regulated(nid, atoms):
    return N(nid, "REGULATED", atoms=atoms)


def _modality(nid, value):
    return N(nid, "MODALITY", value=value)


def _condition(nid, literals, mode="ALL", strength="SUFFICIENT"):
    return N(nid, "CONDITION", literals=literals, mode=mode, strength=strength)


def _exception(nid, literals, mode="ALL"):
    return N(nid, "EXCEPTION", literals=literals, mode=mode)


def _actor(nid, atom, exclusive=False):
    return N(nid, "ACTOR", atom=atom, exclusive=exclusive)


# Entries: (key, text, graph, extra_catalog_atoms, axes, authored_worlds).
ENTRIES: list[tuple] = []


def _register(cohort, family, cases):
    ENTRIES.append((cohort, family, "controlled", cases))


# ---------------------------------------------------------------------------
# Cohort R (12): relation / attachment under surface variation.
# ---------------------------------------------------------------------------

_register("relation_attachment", "relation", [
    ("r01", "So long as the kiln timer has not sounded, members may keep using the glaze room.",
     {"nodes": [_regulated("n1", ["action:use_glaze_room"]),
                _modality("n2", "PERMISSION"),
                _condition("n3", ["!event:kiln_timer_sounded"]),
                _actor("n4", "actor:member")],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTIVATES", "n3", "n1"),
                E("ACTOR_OF", "n4", "n1")]},
     ["actor:assistant"], ("condition", "negation"), []),
    ("r02", "Freight may use the ferry slip only while the yard lamp shows green.",
     {"nodes": [_regulated("n1", ["action:use_ferry_slip_for_freight"]),
                _modality("n2", "PERMISSION"),
                _condition("n3", ["state:yard_lamp_green"], strength="NECESSARY")],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTIVATES", "n3", "n1")]},
     [], ("relation",), []),
    ("r03", "The clean-room hatch may stand open exactly while the external auditor is on site.",
     {"nodes": [_regulated("n1", ["state:cleanroom_hatch_open"]),
                _modality("n2", "PERMISSION"),
                _condition("n3", ["state:external_auditor_on_site"], strength="EXACTLY")],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTIVATES", "n3", "n1")]},
     [], ("relation",), []),
    ("r04", "Unless the standpipe is lagged against frost, the yard tap must be drained each evening.",
     {"nodes": [_regulated("n1", ["state:yard_tap_drained_each_evening"]),
                _modality("n2", "REQUIREMENT"),
                _exception("n3", ["state:standpipe_lagged_against_frost"])],
      "edges": [E("REGULATES", "n2", "n1"), E("EXEMPTS", "n3", "n1")]},
     [], ("exception",), []),
    ("r05", "While the smoke test is running, the spray booth is out of bounds, except when the maintenance fitter carries a mask card.",
     {"nodes": [_regulated("n1", ["action:enter_spray_booth"]),
                _modality("n2", "PROHIBITION"),
                _condition("n3", ["state:smoke_test_running"]),
                _exception("n4", ["state:maintenance_fitter_carries_mask_card"])],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTIVATES", "n3", "n1"),
                E("EXEMPTS", "n4", "n1")]},
     [], ("condition", "exception"), []),
    ("r06", "Whenever the drag line snaps or the pit winch overheats, the pit floor is closed to everyone.",
     {"nodes": [_regulated("n1", ["action:enter_pit_floor"]),
                _modality("n2", "PROHIBITION"),
                _condition("n3", ["event:drag_line_snapped", "event:pit_winch_overheated"],
                           mode="ANY")],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTIVATES", "n3", "n1")]},
     [], ("condition", "quantifier"), []),
    ("r07", "If the delivery van takes the late run, parcels are stacked in the steel cage; if it takes the early run, parcels wait on the shelf.",
     {"nodes": [_regulated("n1", ["state:parcels_stacked_in_steel_cage"]),
                _regulated("n2", ["state:parcels_wait_on_shelf"]),
                _modality("n3", "REQUIREMENT"),
                _condition("n4", ["state:van_takes_late_run"]),
                _condition("n5", ["state:van_takes_early_run"])],
      "edges": [E("REGULATES", "n3", "n1"), E("REGULATES", "n3", "n2"),
                E("ACTIVATES", "n4", "n1"), E("ACTIVATES", "n5", "n2")]},
     [], ("condition", "scope"), []),
    ("r08", "While the visiting assessor is on site, the rooftop terrace and the tunnel wing are both closed to unescorted staff.",
     {"nodes": [_regulated("n1", ["action:roam_rooftop_terrace_unescorted"]),
                _regulated("n2", ["action:roam_tunnel_wing_unescorted"]),
                _modality("n3", "PROHIBITION"),
                _condition("n4", ["state:visiting_assessor_on_site"])],
      "edges": [E("REGULATES", "n3", "n1"), E("REGULATES", "n3", "n2"),
                E("ACTIVATES", "n4", "n1"), E("ACTIVATES", "n4", "n2")]},
     [], ("condition", "scope"), []),
    ("r09", "Only when the river gauge is not showing amber may the orchard well be inspected.",
     {"nodes": [_regulated("n1", ["action:inspect_orchard_well"]),
                _modality("n2", "PERMISSION"),
                _condition("n3", ["!state:river_gauge_showing_amber"],
                           strength="NECESSARY")],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTIVATES", "n3", "n1")]},
     [], ("relation", "negation"), []),
    ("r10", "Teaching-lab glassware never goes into the skip, save when the technician has logged it as scrap.",
     {"nodes": [_regulated("n1", ["action:bin_teaching_lab_glassware"]),
                _modality("n2", "PROHIBITION"),
                _exception("n3", ["state:technician_logged_glassware_as_scrap"])],
      "edges": [E("REGULATES", "n2", "n1"), E("EXEMPTS", "n3", "n1")]},
     ["action:recycle_teaching_lab_glassware"], ("exception",), []),
    ("r11", "Once the dough has proved, the deck oven may be lit, provided the flue damper is open.",
     {"nodes": [_regulated("n1", ["action:light_deck_oven"]),
                _modality("n2", "PERMISSION"),
                _condition("n3", ["event:dough_proved"]),
                _condition("n4", ["state:flue_damper_open"])],
      "edges": [E("REGULATES", "n2", "n1"), E("FOLLOWS", "n3", "n1"),
                E("ACTIVATES", "n4", "n1")]},
     [], ("temporal", "condition"), []),
    ("r12", "After hours, only bearers of the green fob may enter the relay room; the yellow fob opens nothing.",
     {"nodes": [_regulated("n1", ["action:enter_relay_room_after_hours"]),
                _modality("n2", "PERMISSION"),
                _condition("n3", ["state:green_fob_bearer"], strength="NECESSARY")],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTIVATES", "n3", "n1")]},
     ["state:yellow_fob_bearer"], ("relation",), []),
])

# ---------------------------------------------------------------------------
# Cohort E (8): exception vs condition.
# ---------------------------------------------------------------------------

_register("exception_vs_condition", "exception", [
    ("e01", "Cycle helmets are worn on the pump track at all times, except during the toddler hour.",
     {"nodes": [_regulated("n1", ["state:cycle_helmet_worn_on_pump_track"]),
                _modality("n2", "REQUIREMENT"),
                _exception("n3", ["state:toddler_hour"])],
      "edges": [E("REGULATES", "n2", "n1"), E("EXEMPTS", "n3", "n1")]},
     [], ("exception", "modality"), []),
    ("e02", "Photography is banned inside the print room, except for cases where the curator has signed a shoot pass.",
     {"nodes": [_regulated("n1", ["action:photograph_inside_print_room"]),
                _modality("n2", "PROHIBITION"),
                _exception("n3", ["state:curator_signed_shoot_pass"])],
      "edges": [E("REGULATES", "n2", "n1"), E("EXEMPTS", "n3", "n1")]},
     [], ("exception",), []),
    ("e03", "Provided that the cash sheet does not show red, the tuck hatch may stay open.",
     {"nodes": [_regulated("n1", ["action:keep_tuck_hatch_open"]),
                _modality("n2", "PERMISSION"),
                _condition("n3", ["!state:cash_sheet_shows_red"])],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTIVATES", "n3", "n1")]},
     [], ("condition", "negation"), []),
    ("e04", "Do not key up the community transmitter unless the duty log has been countersigned.",
     {"nodes": [_regulated("n1", ["action:key_up_community_transmitter"]),
                _modality("n2", "PROHIBITION"),
                _exception("n3", ["state:duty_log_countersigned"])],
      "edges": [E("REGULATES", "n2", "n1"), E("EXEMPTS", "n3", "n1")]},
     [], ("exception",), []),
    ("e05", "Apart from a declared emergency, the side door stays locked at all times.",
     {"nodes": [_regulated("n1", ["action:unlock_side_door"]),
                _modality("n2", "PROHIBITION"),
                _exception("n3", ["state:declared_emergency"])],
      "edges": [E("REGULATES", "n2", "n1"), E("EXEMPTS", "n3", "n1")]},
     [], ("exception",), []),
    ("e06", "The drag store is out of bounds while drill bookings are posted, unless the quartermaster or her deputy clears the visit.",
     {"nodes": [_regulated("n1", ["action:visit_drag_store"]),
                _modality("n2", "PROHIBITION"),
                _condition("n3", ["state:drill_bookings_posted"]),
                _exception("n4", ["state:quartermaster_clears_visit",
                                  "state:deputy_clears_visit"], mode="ANY")],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTIVATES", "n3", "n1"),
                E("EXEMPTS", "n4", "n1")]},
     [], ("condition", "exception"), []),
    ("e07", "Members' dinghies may be launched whenever the slip light is not showing red, except when the warden posts a closure notice.",
     {"nodes": [_regulated("n1", ["action:launch_members_dinghy"]),
                _modality("n2", "PERMISSION"),
                _condition("n3", ["!state:slip_light_showing_red"]),
                _exception("n4", ["state:warden_posts_closure_notice"])],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTIVATES", "n3", "n1"),
                E("EXEMPTS", "n4", "n1")]},
     ["actor:assistant"], ("condition", "exception", "negation"), []),
    ("e08", "Unless the meter reads zero, the amp rack must be powered down between sets.",
     {"nodes": [_regulated("n1", ["state:amp_rack_powered_down_between_sets"]),
                _modality("n2", "REQUIREMENT"),
                _exception("n3", ["state:meter_reads_zero"])],
      "edges": [E("REGULATES", "n2", "n1"), E("EXEMPTS", "n3", "n1")]},
     ["state:meter_reads_amber"], ("exception",), []),
])

# ---------------------------------------------------------------------------
# Cohort M (8): multi-clause modality / actor binding.
# ---------------------------------------------------------------------------

_register("multiclause_modality_actor", "multiclause", [
    ("m01", "Nurses may top up the syrup dispenser; only the pharmacist may unlock the drug cupboard.",
     {"nodes": [_regulated("n1", ["action:top_up_syrup_dispenser"]),
                _regulated("n2", ["action:unlock_drug_cupboard"]),
                _modality("n3", "PERMISSION"),
                _actor("n4", "actor:nurse"),
                _actor("n5", "actor:pharmacist", exclusive=True)],
      "edges": [E("REGULATES", "n3", "n1"), E("REGULATES", "n3", "n2"),
                E("ACTOR_OF", "n4", "n1"), E("ACTOR_OF", "n5", "n2")]},
     ["actor:assistant"], ("modality", "actor"), []),
    ("m02", "Trainees must log every pool session, and trainees may not enter the filter gallery.",
     {"nodes": [_regulated("n1", ["state:pool_sessions_logged"]),
                _regulated("n2", ["action:enter_filter_gallery"]),
                _modality("n3", "REQUIREMENT"),
                _modality("n4", "PROHIBITION"),
                _actor("n5", "actor:trainee")],
      "edges": [E("REGULATES", "n3", "n1"), E("REGULATES", "n4", "n2"),
                E("ACTOR_OF", "n5", "n1"), E("ACTOR_OF", "n5", "n2")]},
     ["actor:assistant"], ("modality", "actor"), []),
    ("m03", "The intern may fetch slides from the cold store; the intern must not touch the liquid-nitrogen dewar.",
     {"nodes": [_regulated("n1", ["action:fetch_slides_from_cold_store"]),
                _regulated("n2", ["action:touch_liquid_nitrogen_dewar"]),
                _modality("n3", "PERMISSION"),
                _modality("n4", "PROHIBITION"),
                _actor("n5", "actor:intern")],
      "edges": [E("REGULATES", "n3", "n1"), E("REGULATES", "n4", "n2"),
                E("ACTOR_OF", "n5", "n1"), E("ACTOR_OF", "n5", "n2")]},
     ["actor:assistant"], ("modality", "actor"), []),
    ("m04", "Only the senior falconer may hand-feed the display owls, and the falconers must wear gauntlets for every handling.",
     {"nodes": [_regulated("n1", ["action:handfeed_display_owls"]),
                _regulated("n2", ["state:gauntlets_worn_for_handling"]),
                _modality("n3", "PERMISSION"),
                _modality("n4", "REQUIREMENT"),
                _actor("n5", "actor:senior_falconer", exclusive=True),
                _actor("n6", "actor:falconer")],
      "edges": [E("REGULATES", "n3", "n1"), E("REGULATES", "n4", "n2"),
                E("ACTOR_OF", "n5", "n1"), E("ACTOR_OF", "n6", "n2")]},
     ["actor:assistant"], ("modality", "actor"), []),
    ("m05", "Docents may open the butterfly house in the morning; horticulturists may enter the potting vault at any time.",
     {"nodes": [_regulated("n1", ["action:open_butterfly_house"]),
                _regulated("n2", ["action:enter_potting_vault"]),
                _modality("n3", "PERMISSION"),
                _actor("n4", "actor:docent"),
                _actor("n5", "actor:horticulturist"),
                _condition("n6", ["state:morning"])],
      "edges": [E("REGULATES", "n3", "n1"), E("REGULATES", "n3", "n2"),
                E("ACTOR_OF", "n4", "n1"), E("ACTOR_OF", "n5", "n2"),
                E("ACTIVATES", "n6", "n1")]},
     ["actor:assistant"], ("actor", "condition"), []),
    ("m06", "The night porter must patrol the sculpture gallery, and may not move the plinths.",
     {"nodes": [_regulated("n1", ["action:patrol_sculpture_gallery"]),
                _regulated("n2", ["action:move_plinths"]),
                _modality("n3", "REQUIREMENT"),
                _modality("n4", "PROHIBITION"),
                _actor("n5", "actor:night_porter")],
      "edges": [E("REGULATES", "n3", "n1"), E("REGULATES", "n4", "n2"),
                E("ACTOR_OF", "n5", "n1"), E("ACTOR_OF", "n5", "n2")]},
     ["actor:assistant"], ("modality", "actor"), []),
    ("m07", "Scribes may copy the index cards; the registrar alone may annotate the folios; nobody removes the vellum leaves.",
     {"nodes": [_regulated("n1", ["action:copy_index_cards"]),
                _regulated("n2", ["action:annotate_folios"]),
                _regulated("n3", ["action:remove_vellum_leaves"]),
                _modality("n4", "PERMISSION"),
                _modality("n5", "PROHIBITION"),
                _actor("n6", "actor:scribe"),
                _actor("n7", "actor:registrar", exclusive=True)],
      "edges": [E("REGULATES", "n4", "n1"), E("REGULATES", "n4", "n2"),
                E("REGULATES", "n5", "n3"),
                E("ACTOR_OF", "n6", "n1"), E("ACTOR_OF", "n7", "n2")]},
     ["actor:assistant"], ("modality", "actor"), []),
    ("m08", "When the barometer is falling, the winch launch is off limits to cadets; instructors may keep launching until dusk.",
     {"nodes": [_regulated("n1", ["action:take_winch_launch"]),
                _regulated("n2", ["action:keep_launching"]),
                _modality("n3", "PROHIBITION"),
                _modality("n4", "PERMISSION"),
                _actor("n5", "actor:cadet"),
                _actor("n6", "actor:instructor"),
                _condition("n7", ["state:barometer_falling"]),
                _condition("n8", ["event:dusk"])],
      "edges": [E("REGULATES", "n3", "n1"), E("REGULATES", "n4", "n2"),
                E("ACTOR_OF", "n5", "n1"), E("ACTOR_OF", "n6", "n2"),
                E("ACTIVATES", "n7", "n1"), E("PRECEDES", "n8", "n2")]},
     ["actor:assistant"], ("modality", "actor", "condition", "temporal"), []),
])

# ---------------------------------------------------------------------------
# Cohort P (8): permission-evidence controls.
# ---------------------------------------------------------------------------

_register("permission_evidence_controls", "permission_evidence", [
    ("p01", "The service lift can carry four adults at a squeeze. Passengers must face the doors while it moves.",
     {"nodes": [_regulated("n1", ["state:passengers_face_doors"]),
                _modality("n2", "REQUIREMENT"),
                _condition("n3", ["state:service_lift_moving"])],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTIVATES", "n3", "n1")]},
     ["action:carry_four_adults_in_service_lift"], ("modality",), []),
    ("p02", "Nothing in the harbour by-laws prevents early baiting of the lobster pots.",
     {"nodes": [], "edges": []},
     ["state:harbour_patrol_notified", "state:bait_store_open"],
     ("modality",),
     [(["action:bait_lobster_pots_early"], "NO_VIOLATION"),
      (["action:bait_lobster_pots_early", "state:harbour_patrol_notified"],
       "NO_VIOLATION")]),
    ("p03", "Bleach must never be mixed with ammonia at the cleaning bench.",
     {"nodes": [_regulated("n1", ["action:mix_bleach_with_ammonia"]),
                _modality("n2", "PROHIBITION")],
      "edges": [E("REGULATES", "n2", "n1")]},
     ["action:dilute_bleach_at_cleaning_bench"], ("modality",), []),
    ("p04", "Every hire punt is bailed and wiped down before the boat shed is locked.",
     {"nodes": [_regulated("n1", ["state:hire_punt_bailed",
                                  "state:hire_punt_wiped"]),
                _modality("n2", "REQUIREMENT"),
                _condition("n3", ["event:boat_shed_locked"])],
      "edges": [E("REGULATES", "n2", "n1"), E("PRECEDES", "n3", "n1")]},
     [], ("temporal", "scope"), []),
    ("p05", "Members may moor their dinghies at the north pontoon.",
     {"nodes": [_regulated("n1", ["action:moor_dinghy_at_north_pontoon"]),
                _modality("n2", "PERMISSION"),
                _actor("n3", "actor:member")],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTOR_OF", "n3", "n1")]},
     ["actor:assistant"], ("modality", "actor"), []),
    ("p06", "Season holders are entitled to use the clay courts outside peak hours.",
     {"nodes": [_regulated("n1", ["action:use_clay_courts"]),
                _modality("n2", "PERMISSION"),
                _actor("n3", "actor:season_holder"),
                _condition("n4", ["state:outside_peak_hours"])],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTOR_OF", "n3", "n1"),
                E("ACTIVATES", "n4", "n1")]},
     ["actor:assistant"], ("modality", "actor", "condition"), []),
    ("p07", "Adjusting the loom dwell is reserved to the master weaver.",
     {"nodes": [_regulated("n1", ["action:adjust_loom_dwell"]),
                _modality("n2", "PERMISSION"),
                _actor("n3", "actor:master_weaver", exclusive=True)],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTOR_OF", "n3", "n1")]},
     ["actor:assistant"], ("modality", "actor"), []),
    ("p08", "Juniors may use the bouldering wall during staffed hours; the roof ladder is out of bounds to everyone.",
     {"nodes": [_regulated("n1", ["action:use_bouldering_wall"]),
                _regulated("n2", ["action:climb_roof_ladder"]),
                _modality("n3", "PERMISSION"),
                _modality("n4", "PROHIBITION"),
                _actor("n5", "actor:junior"),
                _condition("n6", ["state:staffed_hours"])],
      "edges": [E("REGULATES", "n3", "n1"), E("REGULATES", "n4", "n2"),
                E("ACTOR_OF", "n5", "n1"), E("ACTIVATES", "n6", "n1")]},
     ["actor:assistant"], ("modality", "actor", "condition"), []),
])

# ---------------------------------------------------------------------------
# Cohort X (8): multi-axis controls (>= 2 semantic dimensions).
# ---------------------------------------------------------------------------

_register("multiaxis_controls", "multi_axis", [
    ("x01", "Duty pilots who have filed a flight plan may enter the hangar mezzanine, except when the foam drill is running.",
     {"nodes": [_regulated("n1", ["action:enter_hangar_mezzanine"]),
                _modality("n2", "PERMISSION"),
                _actor("n3", "actor:duty_pilot"),
                _condition("n4", ["state:flight_plan_filed"]),
                _exception("n5", ["state:foam_drill_running"])],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTOR_OF", "n3", "n1"),
                E("ACTIVATES", "n4", "n1"), E("EXEMPTS", "n5", "n1")]},
     ["actor:assistant"], ("actor", "condition", "exception"), []),
    ("x02", "Once the pasteurisation cycle has finished, the cream vats may be opened, unless the thermostat reads amber.",
     {"nodes": [_regulated("n1", ["action:open_cream_vats"]),
                _modality("n2", "PERMISSION"),
                _condition("n3", ["event:pasteurisation_cycle_finished"]),
                _exception("n4", ["state:thermostat_reads_amber"])],
      "edges": [E("REGULATES", "n2", "n1"), E("FOLLOWS", "n3", "n1"),
                E("EXEMPTS", "n4", "n1")]},
     [], ("temporal", "exception"), []),
    ("x03", "Figures for the gate count and the locker tally come from the turnstile log alone, each on its own form.",
     {"nodes": [_regulated("n1", ["claim:gate_count"]),
                _regulated("n2", ["claim:locker_tally"]),
                _modality("n3", "REQUIREMENT"),
                N("n4", "QUALIFIER", kind="PROVENANCE",
                  value="evidence:turnstile_log")],
      "edges": [E("REGULATES", "n3", "n1"), E("REGULATES", "n3", "n2"),
                E("SOURCE_OF", "n4", "n1"), E("SOURCE_OF", "n4", "n2")]},
     [], ("provenance", "scope"), []),
    ("x04", "No more than three storm lanterns per raft on the night crossing, save when the trip lead okays a fourth.",
     {"nodes": [_regulated("n1", ["state:lanterns_per_raft_gt_3"]),
                _modality("n2", "PROHIBITION"),
                _exception("n3", ["state:trip_lead_okays_fourth"]),
                N("n4", "QUALIFIER", kind="QUANTIFIER", value="AT_MOST_3")],
      "edges": [E("REGULATES", "n2", "n1"), E("EXEMPTS", "n3", "n1"),
                E("QUALIFIES", "n4", "n1")]},
     [], ("cardinality", "exception"), []),
    ("x05", "Provided the wind meter is not in the red zone, the balcony telescope may be used after dark.",
     {"nodes": [_regulated("n1", ["action:use_balcony_telescope"]),
                _modality("n2", "PERMISSION"),
                _condition("n3", ["!state:wind_meter_red_zone",
                                  "state:after_dark"])],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTIVATES", "n3", "n1")]},
     [], ("negation", "condition"), []),
    ("x06", "Writing the tank figures into the board book is not optional whenever the hatch is open.",
     {"nodes": [_regulated("n1", ["state:tank_figures_written_in_board_book"]),
                _modality("n2", "REQUIREMENT"),
                _condition("n3", ["state:hatch_open"])],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTIVATES", "n3", "n1")]},
     [], ("modality", "negation"), []),
    ("x07", "Before the auction opens, the paddle cards and the bidder sheets are counted, each on its own tray.",
     {"nodes": [_regulated("n1", ["action:count_paddle_cards"]),
                _regulated("n2", ["action:count_bidder_sheets"]),
                _modality("n3", "REQUIREMENT"),
                _condition("n4", ["event:auction_opens"])],
      "edges": [E("REGULATES", "n3", "n1"), E("REGULATES", "n3", "n2"),
                E("PRECEDES", "n4", "n1"), E("PRECEDES", "n4", "n2")]},
     [], ("temporal", "scope"), []),
    ("x08", "Stewards may park behind the members' pavilion, except on concert nights.",
     {"nodes": [_regulated("n1", ["action:park_behind_members_pavilion"]),
                _modality("n2", "PERMISSION"),
                _actor("n3", "actor:steward"),
                _exception("n4", ["state:concert_night"])],
      "edges": [E("REGULATES", "n2", "n1"), E("ACTOR_OF", "n3", "n1"),
                E("EXEMPTS", "n4", "n1")]},
     ["actor:assistant"], ("actor", "exception"), []),
])

COHORT_PLAN = {"relation_attachment": 12, "exception_vs_condition": 8,
               "multiclause_modality_actor": 8,
               "permission_evidence_controls": 8, "multiaxis_controls": 8}


# --------------------------------------------------------------------- build

def _graph_atoms(graph: dict) -> set:
    atoms = set()
    for node in graph.get("nodes", []):
        if node.get("type") == "REGULATED":
            atoms.update(node.get("atoms") or [])
        for field in ("literals",):
            if node.get(field):
                for lit in node[field]:
                    atoms.add(lit[1:] if lit.startswith("!") else lit)
        if node.get("type") == "ACTOR" and node.get("atom"):
            atoms.add(node["atom"])
        if node.get("type") == "QUALIFIER" and isinstance(node.get("value"), str):
            atoms.add(node["value"])
    return atoms


def _word_ngrams(text: str, n: int = 8) -> set:
    tokens = ["".join(ch for ch in word.lower() if ch.isalnum())
              for word in text.split()]
    tokens = [token for token in tokens if token]
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _development_text_ngrams() -> set:
    ngrams: set = set()
    for case in build_v4_benchmark(seed=260914):
        ngrams |= _word_ngrams(case.policy)
    for case in build_v5_benchmark(seed=260915):
        ngrams |= _word_ngrams(case.policy)
    for case in build_phv1_holdout():
        ngrams |= _word_ngrams(case.policy)
    return ngrams


# ---------------------------------------------- binding-detection machinery

def _perturb_condition_exception_swap(programs):
    """Swap condition_literals <-> exception_literals of the first program
    that has either (modes swap too). One perturbation per seed program."""
    out = []
    for index, program in enumerate(programs):
        if program["condition_literals"] or program["exception_literals"]:
            flipped = dict(program)
            flipped["condition_literals"] = list(program["exception_literals"])
            flipped["condition_mode"] = program["exception_mode"]
            flipped["exception_literals"] = list(program["condition_literals"])
            flipped["exception_mode"] = program["condition_mode"]
            if program["modality"] == "REQUIREMENT" \
                    and flipped["condition_literals"] \
                    and flipped["exception_literals"]:
                continue  # outside the frozen envelope; not a legal reading
            out.append([p if i != index else flipped
                        for i, p in enumerate(programs)])
    return out


def _perturb_strength_flip(programs):
    out = []
    for index, program in enumerate(programs):
        flipped = dict(program)
        if program["relation"] == "IF":
            flipped["relation"] = "ONLY_IF"
        elif program["relation"] == "ONLY_IF":
            flipped["relation"] = "IF"
        else:
            continue
        out.append([p if i != index else flipped for i, p in enumerate(programs)])
    return out


def _perturb_modality_swap(programs):
    if len(programs) < 2:
        return []
    modalities = [p["modality"] for p in programs]
    if len(set(modalities)) < 2:
        return []
    first = next(i for i, m in enumerate(modalities)
                 if m != modalities[0])
    swapped = [dict(p) for p in programs]
    swapped[0]["modality"], swapped[first]["modality"] = \
        modalities[first], modalities[0]
    return [swapped]


def _perturb_actor_move(programs):
    def actor_of(program):
        return [lit for lit in program["condition_literals"]
                if lit.startswith("actor:")]
    if len(programs) < 2:
        return []
    actors = [actor_of(p) for p in programs]
    if any(len(a) != 1 for a in actors) or actors[0] == actors[1]:
        return []
    moved = []
    for program, actor in zip(programs, actors):
        flipped = dict(program)
        flipped["condition_literals"] = sorted(
            [lit for lit in program["condition_literals"]
             if not lit.startswith("actor:")] + actor)
        moved.append(flipped)
    # swap the two single actors
    moved[0]["condition_literals"] = sorted(
        [lit for lit in moved[0]["condition_literals"]
         if not lit.startswith("actor:")] + actors[1])
    moved[1]["condition_literals"] = sorted(
        [lit for lit in moved[1]["condition_literals"]
         if not lit.startswith("actor:")] + actors[0])
    return [moved]


def _perturb_gate_move(programs):
    """Move the non-actor condition literals of program 0 onto program 1."""
    if len(programs) < 2:
        return []
    plain0 = [lit for lit in programs[0]["condition_literals"]
              if not lit.startswith(("actor:", "identity:", "evidence:"))]
    if not plain0:
        return []
    moved = [dict(p) for p in programs]
    moved[0]["condition_literals"] = [lit for lit in programs[0]["condition_literals"]
                                     if lit not in plain0]
    moved[1]["condition_literals"] = sorted(set(programs[1]["condition_literals"])
                                            | set(plain0))
    return [moved]


def _perturb_polarity_flip(programs):
    out = []
    for index, program in enumerate(programs):
        for lit in program["condition_literals"]:
            flipped_lit = lit[1:] if lit.startswith("!") else "!" + lit
            flipped = dict(program)
            flipped["condition_literals"] = sorted(
                flipped_lit if other == lit else other
                for other in program["condition_literals"])
            out.append([p if i != index else flipped
                        for i, p in enumerate(programs)])
        break
    return out


def _perturb_modality_flip(programs):
    """Flip the modality of the first program to a different value."""
    out = []
    for index, program in enumerate(programs):
        for value in ("PERMISSION", "PROHIBITION", "REQUIREMENT"):
            if value != program["modality"]:
                flipped = dict(program)
                flipped["modality"] = value
                out.append([p if i != index else flipped
                            for i, p in enumerate(programs)])
        break
    return out


def _perturb_clause_merge(programs):
    if len(programs) < 2:
        return []
    if any(len(p["target_clauses"]) != 1 or len(p["target_clauses"][0]) != 1
           for p in programs[:2]):
        return []
    merged = [dict(p) for p in programs]
    atoms = sorted(set(merged[0]["target_clauses"][0])
                   | set(merged[1]["target_clauses"][0]))
    first = dict(merged[0])
    first["target_clauses"] = [atoms]
    return [[first] + merged[2:]]


_PERTURBATIONS = {
    "condition_exception_swap": _perturb_condition_exception_swap,
    "strength_flip": _perturb_strength_flip,
    "modality_swap": _perturb_modality_swap,
    "actor_move": _perturb_actor_move,
    "gate_move": _perturb_gate_move,
    "polarity_flip": _perturb_polarity_flip,
    "modality_flip": _perturb_modality_flip,
    "clause_merge": _perturb_clause_merge,
}

def _required_detections(cohort: str, programs) -> list:
    """Cohort-defining misbindings that MUST be behaviorally observable for
    this case. strength_flip only applies where the v3 evaluator is strength
    sensitive (PERMISSION / REQUIREMENT with an IF-family relation); gate /
    actor / modality moves only apply to multi-program golds."""
    strength_sensitive = [
        p for p in programs
        if p["modality"] in ("PERMISSION", "REQUIREMENT")
        and p["relation"] in ("IF", "ONLY_IF")]
    if cohort == "relation_attachment":
        required = []
        if strength_sensitive:
            required.append("strength_flip")
        if len(programs) >= 2:
            required.append("gate_move")
        return required
    if cohort == "exception_vs_condition":
        return ["condition_exception_swap"]
    if cohort == "multiclause_modality_actor":
        return ["modality_swap", "actor_move"]
    if cohort == "multiaxis_controls":
        required = []
        if strength_sensitive:
            required.append("strength_flip")
        required.append("condition_exception_swap")
        return required
    if cohort == "permission_evidence_controls":
        return ["modality_flip"]
    return []


def binding_detection_report(admissible_sets, worlds) -> dict:
    """For each frozen perturbation family: does some frozen world separate
    the gold composition from every perturbed composition? Deterministic."""
    fact_sets = []
    seen = set()
    for world in worlds:
        key = frozenset(world["facts"])
        if key not in seen:
            seen.add(key)
            fact_sets.append(key)
    programs = list(admissible_sets[0])
    report = {}
    for name, perturb in _PERTURBATIONS.items():
        candidates = perturb(programs)
        detected = False
        for candidate in candidates:
            for facts in fact_sets:
                gold = {composed_verdict(s, facts) for s in admissible_sets}
                verdict = composed_verdict(candidate, facts)
                if verdict not in gold:
                    detected = True
                    break
            if detected:
                break
        report[name] = {"n_perturbations": len(candidates), "detected": detected}
    return report


def _flat_merge_candidate(programs):
    """Deterministic single-program candidate for h0_representability: all
    programs share modality/relation/gates -> one program with every target
    clause. Returns None when no such merge exists."""
    if not programs:
        return None
    base = dict(programs[0])
    for program in programs[1:]:
        for field in ("modality", "relation", "condition_literals",
                      "condition_mode", "exception_literals",
                      "exception_mode", "temporal"):
            if program[field] != base[field]:
                return None
    clauses = [list(clause) for program in programs
               for clause in program["target_clauses"]]
    base["target_clauses"] = sorted(clauses)
    return base


def h0_representable(admissible_sets, worlds) -> bool:
    """A case is H0-representable when a single flat v3 program reproduces
    every composed gold verdict on the frozen world surface (merge
    equivalence), or when the gold set is a single program. Empty gold sets
    are not representable (the flat schema forces at least one clause)."""
    programs = list(admissible_sets[0])
    if not programs:
        return False
    if len(programs) == 1:
        return True
    merged = _flat_merge_candidate(programs)
    if merged is None:
        return False
    for world in worlds:
        facts = frozenset(world["facts"])
        if composed_verdict([merged], facts) != composed_verdict(programs, facts):
            return False
    return True


def build_psb_causal_benchmark() -> list[PolicyPSBCase]:
    """Build the frozen PSB causal corpus deterministically (44 cases) with
    every machine self-check from the preregistration."""
    cases: list[PolicyPSBCase] = []
    dev_ngrams = _development_text_ngrams()
    seen_texts, seen_ngrams = set(), set()
    for cohort, family, style, entries in ENTRIES:
        for key, text, graph, extra_atoms, axes, authored_worlds in entries:
            programs, _rejected = compile_psb_graph(graph, permission_gate=False)
            admissible_sets = (tuple(programs),)
            worlds = generate_worlds_for_sets(admissible_sets)
            for facts, expected in authored_worlds:
                worlds.append({"facts": sorted(facts), "expected": expected})
            # gold self-score (wiring check; tautological by construction)
            correct, _ = score_program_set(list(programs), worlds, admissible_sets)
            if not correct:
                raise ValueError(f"gold does not self-score correct: {family}::{key}")
            # every non-empty gold case must have discriminating worlds
            if programs:
                acceptable = {composed_verdict(admissible_sets[0],
                                               frozenset(w["facts"]))
                              for w in worlds}
                if acceptable == {"NO_VIOLATION"}:
                    raise ValueError(f"no discriminating world: {family}::{key}")
            # cohort-defining misbindings must be behaviorally observable
            detection = binding_detection_report(admissible_sets, worlds)
            for required in _required_detections(cohort, programs):
                if detection[required]["n_perturbations"] \
                        and not detection[required]["detected"]:
                    raise ValueError(f"{required} not detectable: {family}::{key}")
            # novelty vs development corpora + internal duplication
            ngrams = _word_ngrams(text)
            if ngrams & dev_ngrams:
                raise ValueError(f"8-gram overlap with development corpus: "
                                 f"{family}::{key}")
            if ngrams & seen_ngrams:
                raise ValueError(f"internal 8-gram duplication: {family}::{key}")
            if text in seen_texts:
                raise ValueError(f"internal text duplication: {family}::{key}")
            seen_texts.add(text)
            seen_ngrams |= ngrams
            atoms = _graph_atoms(graph) | set(extra_atoms)
            atoms.add(f"distractor:{key}")
            if not programs:
                # empty-gold control: keep the tempting act in the catalog
                atoms.add("action:bait_lobster_pots_early")
            catalog = tuple(sorted(atoms))
            case = PolicyPSBCase(
                case_id=f"{family}::{key}", cohort=cohort, family=family,
                style=style, policy=text, atom_catalog=catalog,
                gold_graph=graph, admissible_program_sets=admissible_sets,
                worlds=tuple(worlds), axes=tuple(axes),
                h0_representable=h0_representable(admissible_sets, worlds))
            cases.append(case)
    observed = {}
    for case in cases:
        observed[case.cohort] = observed.get(case.cohort, 0) + 1
    if observed != COHORT_PLAN:
        raise ValueError(f"cohort composition mismatch: {observed}")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("duplicate case ids")
    return sorted(cases, key=lambda case: case.case_id)


def benchmark_psb_causal_document(cases: list[PolicyPSBCase]) -> dict:
    rows = [case.as_dict() for case in cases]
    return {"schema_version": "guardian-vnext-policy-psb-causal-v1",
            "prereg": "docs/vnext/PSB_PREREG_GATES_V1.json",
            "frozen_before_predictions": True,
            "annotation_basis": "CONSTRUCTION_FROM_TEMPLATES_NOT_MODEL_LABELS",
            "cohorts": dict(COHORT_PLAN),
            "cases_sha256": digest(rows), "cases": rows}

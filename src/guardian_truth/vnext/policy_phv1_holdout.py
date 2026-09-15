"""Policy PHV1 prospective holdout corpus: 80 NEW cases, gold by construction.

PHV1 = Policy H0 Prospective Holdout V1 (prereg: docs/vnext/PHV1_PREREG_GATES_V1.json).
Purpose: VALIDATE the frozen conservative H0 Policy frontend on unseen policy
texts, not to improve it. This corpus is authored after the H0 freeze
(C-ALR reimplementation study) and gold is frozen before any PHV1 request.

Corpus rules (preregistered):
- 80 cases: 20 simple controls, 20 single-axis structural, 20 multi-axis
  compositional, 12 natural-language stress, 8 genuinely ambiguous
  (two admissible readings, each with positive linguistic support).
- NEW policy texts in fresh domains: not noun-swapped V4/V5 templates; the
  six observed V5 residual failures are not used as direct templates. Tests
  machine-check novelty: no PHV1 policy text shares a word 8-gram with any
  V4 or V5 policy text.
- Gold by construction: admissible structure(s) are typed by hand, compiled
  with compile_v3_structure; behavioral worlds are generated deterministically;
  ambiguous pairs must be behaviorally distinct (_distinguishing_world).
- Conservative invariant: NO_VIOLATION is not PERMITTED; absence of
  restriction is never explicit permission.
- Explicit coordination is NOT ambiguity: 'or' means ANY, 'both' means ALL,
  'only' means ONLY_IF. Ambiguity requires positive linguistic support for
  both readings (authority 'belongs to'/'a matter for', negation scope over
  coordination, exceptive vs negated-conditional 'no X without Y' and
  'not ... until X').

Everything here is deterministic: no LLM, no network, no wall-clock.
"""

from dataclasses import dataclass
import json

from .integrity import digest
from .policy_v3_benchmark import (
    compile_v3_structure, generate_worlds, _distinguishing_world)


@dataclass(frozen=True)
class PolicyPHV1Case:
    case_id: str
    cohort: str
    family: str
    style: str
    policy: str
    atom_catalog: tuple
    ambiguous: bool
    trap: bool
    admissible_structures: tuple
    admissible_programs: tuple
    worlds: tuple
    axes: tuple

    def as_dict(self) -> dict:
        return {"case_id": self.case_id, "cohort": self.cohort, "family": self.family,
                "style": self.style, "policy": self.policy,
                "atom_catalog": list(self.atom_catalog),
                "ambiguous": self.ambiguous, "trap": self.trap,
                "admissible_structures": [dict(s) for s in self.admissible_structures],
                "admissible_programs": [dict(p) for p in self.admissible_programs],
                "worlds": [dict(w) for w in self.worlds],
                "axes": list(self.axes)}


def _structure(modality, relation, targets, conditions=(), exceptions=(), *,
               condition_mode="ALL", exception_mode="ALL", actor="assistant",
               regulated_kind="ACTION", facet="primary", temporal="NONE", identity="ANY",
               provenance="ANY", quantification="ALL") -> dict:
    return {"modality": modality, "actor": actor, "regulated_kind": regulated_kind,
            "facet": facet, "relation": relation, "target_clauses": [list(t) for t in targets],
            "condition_literals": list(conditions), "exception_literals": list(exceptions),
            "condition_mode": condition_mode, "exception_mode": exception_mode,
            "temporal": temporal, "identity": identity, "provenance": provenance,
            "quantification": quantification}


# Entries: (key, policy_text, [structures], [extra_catalog_atoms]).
PHV1_TEMPLATES: list[tuple] = []


def _register(cohort, family, style, cases, trap=False, axes=()):
    PHV1_TEMPLATES.append((cohort, family, style, cases, trap, tuple(axes)))


# ---------------------------------------------------------------------------
# Cohort 1: simple controls (20) - baseline generalization, §10.
# ---------------------------------------------------------------------------

_register("simple", "simple", "controlled", [
    ("s01", "The glue pot is never to be heated over an open flame.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:heat_glue_pot_over_open_flame"]])], []),
    ("s02", "Under no circumstances may the master key be lent to tenants.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:lend_master_key_to_tenants"]])], []),
    ("s03", "Every batch ticket must be hole-punched at the weigh station.",
     [_structure("REQUIREMENT", "UNCONDITIONAL", [["state:batch_ticket_punched_at_weigh_station"]])], []),
    ("s04", "Staff are required to hang their fobs on the pegboard at the end of each shift.",
     [_structure("REQUIREMENT", "UNCONDITIONAL", [["state:fobs_hung_on_pegboard"]])], []),
    ("s05", "The staff-room toaster may be used at any time.",
     [_structure("PERMISSION", "UNCONDITIONAL", [["action:use_staffroom_toaster"]])], []),
    ("s06", "Members may bring one guest to the society supper.",
     [_structure("PERMISSION", "IF", [["action:bring_guest_to_society_supper"]], ["actor:member"])],
     ["actor:assistant"]),
    ("s07", "If the tide board reads low water, the ford crossing may be attempted.",
     [_structure("PERMISSION", "IF", [["action:attempt_ford_crossing"]], ["state:tide_board_low_water"])], []),
    ("s08", "When the booking sheet shows a free piste, the practice track may be reserved.",
     [_structure("PERMISSION", "IF", [["action:reserve_practice_track"]], ["state:booking_sheet_free_piste"])], []),
    ("s09", "Frost blankets may be deployed only while the irrigation is shut down.",
     [_structure("PERMISSION", "ONLY_IF", [["action:deploy_frost_blankets"]], ["state:irrigation_shut_down"])], []),
    ("s10", "Only with the duty coxswain's consent can the rescue launch leave its berth.",
     [_structure("PERMISSION", "ONLY_IF", [["action:leave_rescue_launch_berth"]], ["state:duty_coxswain_consent"])], []),
    ("s11", "The annexe may be unlocked if and only if the museum is open to the public.",
     [_structure("PERMISSION", "IF_AND_ONLY_IF", [["action:unlock_annexe"]], ["state:museum_open_to_public"])], []),
    ("s12", "Access to the drop zone is granted exactly when the jump manifest is closed.",
     [_structure("PERMISSION", "IF_AND_ONLY_IF", [["action:access_drop_zone"]], ["state:jump_manifest_closed"])], []),
    ("s13", "Smoking is forbidden on the viewing terrace, except during the licensed festival.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:smoke_on_viewing_terrace"]],
                 exceptions=["state:licensed_festival"])], []),
    ("s14", "Parking on the access road is banned, except when the overflow field is sodden.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:park_on_access_road"]],
                 exceptions=["state:overflow_field_sodden"])], []),
    ("s15", "Only the duty sound engineer may patch the mixing desk.",
     [_structure("PERMISSION", "ONLY_IF", [["action:patch_mixing_desk"]], ["actor:duty_sound_engineer"])],
     ["actor:assistant"]),
    ("s16", "Resetting the breaker is reserved to the qualified electrician.",
     [_structure("PERMISSION", "ONLY_IF", [["action:reset_breaker"]], ["actor:qualified_electrician"])],
     ["actor:assistant"]),
    ("s17", "Provided that the sump lamp is lit, the bilge pump may be run.",
     [_structure("PERMISSION", "IF", [["action:run_bilge_pump"]], ["state:sump_lamp_lit"])], []),
    ("s18", "The drying racks may be loaded once the extract fan has started.",
     [_structure("PERMISSION", "IF", [["action:load_drying_racks"]], ["event:extract_fan_started"],
                 temporal="AFTER")], []),
    ("s19", "It is mandatory to log every helium transfer in the cylinder book.",
     [_structure("REQUIREMENT", "UNCONDITIONAL", [["state:helium_transfers_logged_in_cylinder_book"]])], []),
    ("s20", "Cellulose thinners must never be stored beside the compressor.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:store_thinners_beside_compressor"]])], []),
])

# ---------------------------------------------------------------------------
# Cohort 2: single-axis structural (20), §11-§14 constructions.
# ---------------------------------------------------------------------------

_register("structural", "modality", "controlled", [
    ("m01", "A current tetanus booster is sufficient for entry to the muck yard.",
     [_structure("PERMISSION", "IF", [["action:enter_muck_yard"]], ["state:tetanus_booster_current"])], []),
    ("m02", "Completing the chain-saw course is necessary before any felling work.",
     [_structure("PERMISSION", "ONLY_IF", [["action:undertake_felling_work"]], ["state:chainsaw_course_completed"])], []),
    ("m03", "All visitors are obliged to dip their boots at the gate.",
     [_structure("REQUIREMENT", "UNCONDITIONAL", [["state:visitor_boots_dipped_at_gate"]])], []),
])

_register("structural", "condition", "controlled", [
    ("c01", "The hoist may be used provided the outriggers are pinned and the pad feet are on firm ground.",
     [_structure("PERMISSION", "IF", [["action:use_hoist"]],
                 ["state:outriggers_pinned", "state:pad_feet_firm_ground"], condition_mode="ALL")], []),
    ("c02", "If the weir gauge reads amber or the by-wash is blocked, the canoe session is called off.",
     [_structure("PROHIBITION", "IF", [["action:run_canoe_session"]],
                 ["state:weir_gauge_amber", "state:bywash_blocked"], condition_mode="ANY")], []),
])

_register("structural", "exception", "controlled", [
    ("e01", "Loudspeakers are banned in the bird garden, except when the warden runs a dawn walk.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:use_loudspeakers_in_bird_garden"]],
                 exceptions=["state:warden_dawn_walk_running"])], []),
    ("e02", "The society ledger stays sealed except for cases where the auditor general demands inspection.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:open_society_ledger"]],
                 exceptions=["state:auditor_general_demands_inspection"])], []),
    ("e03", "When the bakehouse is running, apprentices may operate the divider, unless the miller is adjusting the stones.",
     [_structure("PERMISSION", "IF", [["action:operate_divider"]], ["state:bakehouse_running"],
                 exceptions=["state:miller_adjusting_stones"])], []),
])

_register("structural", "negation", "controlled", [
    ("n01", "No food or drink may be taken into the map room.",
     [_structure("PROHIBITION", "UNCONDITIONAL",
                 [["action:take_food_into_map_room"], ["action:take_drink_into_map_room"]])], []),
    ("n02", "Neither the junior rowers nor the novice coxes may launch the double scull.",
     [_structure("PROHIBITION", "IF", [["action:launch_double_scull"]],
                 ["actor:junior_rower", "actor:novice_cox"], condition_mode="ANY")], ["actor:assistant"]),
    ("n03", "The meadow may be mown only ahead of the orchid count.",
     [_structure("PERMISSION", "ONLY_IF", [["action:mow_the_meadow"]], ["!event:orchid_count_begun"],
                 temporal="BEFORE")], []),
])

_register("structural", "scope", "controlled", [
    ("sc01", "Running the buffer and the polisher off one extension lead is not allowed.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:run_buffer", "action:run_polisher"]])], []),
    ("sc02", "Two standing rules for the lamp room: do not repaint the brass, and do not reorder the lenses.",
     [_structure("PROHIBITION", "UNCONDITIONAL",
                 [["action:repaint_the_brass"], ["action:reorder_the_lenses"]])], []),
])

_register("structural", "actor", "controlled", [
    ("a01", "Bare-hand feeding is a keeper-only duty at the otter pool.",
     [_structure("PERMISSION", "ONLY_IF", [["action:barehand_feed_otters"]], ["actor:keeper"])],
     ["actor:assistant"]),
    ("a02", "Deputy librarians, and only deputy librarians, may admit readers after hours.",
     [_structure("PERMISSION", "ONLY_IF", [["action:admit_readers_after_hours"]], ["actor:deputy_librarian"])],
     ["actor:assistant"]),
])

_register("structural", "identity", "controlled", [
    ("i01", "Each speaker may collect only their own name badge.",
     [_structure("PERMISSION", "ONLY_IF", [["action:collect_name_badge"]], ["identity:speaker_self"])], []),
])

_register("structural", "provenance", "controlled", [
    ("p01", "For the flock counts, the pasture app is the sole source; counts from memory do not count.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:flock_counts"]], ["evidence:pasture_app"],
                 regulated_kind="INFORMATION", provenance="TOOL_RESULT")], []),
])

_register("structural", "cardinality", "controlled", [
    ("q01", "No more than four bales per lift on the goods hoist.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["state:bales_per_lift_gt_4"]],
                 quantification="AT_MOST_4", regulated_kind="STATE")], []),
])

_register("structural", "temporal", "controlled", [
    ("t01", "Only once the dust extractor has reached speed may grinding begin.",
     [_structure("PERMISSION", "ONLY_IF", [["action:begin_grinding"]], ["event:dust_extractor_reached_speed"],
                 temporal="AFTER")], []),
    ("t02", "After the drag pack has passed, the footpath may be reopened.",
     [_structure("PERMISSION", "IF", [["action:reopen_footpath"]], ["event:drag_pack_passed"],
                 temporal="AFTER")], []),
])

# ---------------------------------------------------------------------------
# Cohort 3: multi-axis compositional (20), §15: >= 2 semantic dimensions.
# ---------------------------------------------------------------------------

_register("multi_clause", "multi_axis", "controlled", [
    ("x01", "Only fitters who have logged the morning calibration may true the lathe chucks.",
     [_structure("PERMISSION", "ONLY_IF", [["action:true_lathe_chucks"]],
                 ["actor:fitter", "state:morning_calibration_logged"], condition_mode="ALL")], ["actor:assistant"]),
    ("x02", "Wardens on the night roster may issue spare hut keys to walkers in distress.",
     [_structure("PERMISSION", "IF", [["action:issue_hut_keys_to_walkers_in_distress"]],
                 ["actor:warden", "state:night_roster"], condition_mode="ALL")], ["actor:assistant"]),
    ("x03", "Duty skippers may call the ice breaker when the channel gauge shows plate ice.",
     [_structure("PERMISSION", "IF", [["action:call_ice_breaker"]],
                 ["actor:duty_skipper", "state:channel_gauge_plate_ice"], condition_mode="ALL")], ["actor:assistant"]),
    ("x04", "After the gales have passed, the boardwalk may reopen, except where the deck planks are still sprung.",
     [_structure("PERMISSION", "IF", [["action:reopen_boardwalk"]], ["event:gales_passed"],
                 exceptions=["state:deck_planks_sprung"], temporal="AFTER")], []),
    ("x05", "Once the curd has set, the cutting frames may be lowered, unless the vat reads above thirty-two degrees.",
     [_structure("PERMISSION", "IF", [["action:lower_cutting_frames"]], ["event:curd_set"],
                 exceptions=["state:vat_above_thirty_two_degrees"], temporal="AFTER")], []),
    ("x06", "Blasting may proceed only after the bird-scarer rounds finish, except when the shot-fireer calls a weather hold.",
     [_structure("PERMISSION", "ONLY_IF", [["action:proceed_blasting"]], ["event:birdscarer_rounds_finished"],
                 exceptions=["state:weather_hold_called"], temporal="AFTER")], []),
    ("x07", "The melt index and the batch code are to be taken from the furnace terminal alone, each logged on its own line.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:melt_index"], ["claim:batch_code"]],
                 ["evidence:furnace_terminal"], regulated_kind="INFORMATION", provenance="TOOL_RESULT")], []),
    ("x08", "Weights for the rams and the ewes go on separate cards; the veterinary scale printout is the only acceptable source.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:ram_weights"], ["claim:ewe_weights"]],
                 ["evidence:vet_scale_printout"], regulated_kind="INFORMATION", provenance="TOOL_RESULT")], []),
    ("x09", "Recording the till serials is not optional whenever the floats cabinet is unlocked.",
     [_structure("REQUIREMENT", "IF", [["state:till_serials_recorded"]], ["state:floats_cabinet_unlocked"])], []),
    ("x10", "Unless the moisture meter dissents, the floorboards must acclimatize in the room for a fortnight.",
     [_structure("REQUIREMENT", "UNLESS", [["state:floorboards_acclimatized_fortnight"]],
                 exceptions=["state:moisture_meter_dissenting"])], []),
    ("x11", "When the anemometer is not showing red, kite flying is permitted at the seaward end.",
     [_structure("PERMISSION", "IF", [["action:fly_kite_seaward_end"]], ["!state:anemometer_showing_red"])], []),
    ("x12", "At most six guests per members' screening, unless the director opens the circle seats.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["state:guests_per_screening_gt_6"]],
                 exceptions=["state:director_opens_circle_seats"],
                 quantification="AT_MOST_6", regulated_kind="STATE")], []),
    ("x13", "No more than two dogs off the lead per handler, except at the retired-greyhound sessions.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["state:dogs_offlead_per_handler_gt_2"]],
                 exceptions=["state:retired_greyhound_session"],
                 quantification="AT_MOST_2", regulated_kind="STATE")], []),
    ("x14", "Provided the loom is not mid-pick, the warp tension may be adjusted.",
     [_structure("PERMISSION", "IF", [["action:adjust_warp_tension"]], ["!state:loom_mid_pick"])], []),
    ("x15", "If the estate gate is not chained after midnight, the patrol must log it.",
     [_structure("REQUIREMENT", "IF", [["state:patrol_logs_gate"]], ["!state:estate_gate_chained_after_midnight"])], []),
    ("x16", "So long as the reservoir is not drawn down past the second ledge, anglers may fish the tower bank.",
     [_structure("PERMISSION", "IF", [["action:fish_tower_bank"]], ["!state:reservoir_drawn_down_second_ledge"])], []),
    ("x17", "Once the fair ends, the show-jump wings and the plastic cups are to be stacked together on the trolley.",
     [_structure("REQUIREMENT", "IF", [["action:stack_showjump_wings", "action:stack_plastic_cups"]],
                 ["event:fair_ends"], temporal="AFTER")], []),
    ("x18", "Before the sea mist rolls in, the waymarkers and the rope lines are to be checked, each on its own round.",
     [_structure("REQUIREMENT", "IF", [["action:check_waymarkers"], ["action:check_rope_lines"]],
                 ["!event:sea_mist_rolled_in"], temporal="BEFORE")], []),
    ("x19", "Caddies may take the buggy onto the fringe, except when the greenskeeper has flagged the dew.",
     [_structure("PERMISSION", "IF", [["action:take_buggy_onto_fringe"]], ["actor:caddie"],
                 exceptions=["state:greenskeeper_flagged_dew"])], ["actor:assistant"]),
    ("x20", "Trainee helpers may open the petting barn, save when the vet has sealed the lambing wing.",
     [_structure("PERMISSION", "IF", [["action:open_petting_barn"]], ["actor:trainee_helper"],
                 exceptions=["state:vet_sealed_lambing_wing"])], ["actor:assistant"]),
], axes=())

# axes annotation per multi-axis case key (>= 2 semantic dimensions, §15)
MULTI_AXIS_AXES = {
    "x01": ("actor", "condition"), "x02": ("actor", "condition"), "x03": ("actor", "condition"),
    "x04": ("exception", "temporal"), "x05": ("exception", "temporal"), "x06": ("exception", "temporal"),
    "x07": ("scope", "provenance"), "x08": ("scope", "provenance"),
    "x09": ("modality", "negation"), "x10": ("modality", "negation"), "x11": ("modality", "negation"),
    "x12": ("cardinality", "exception"), "x13": ("cardinality", "exception"),
    "x14": ("condition", "negation"), "x15": ("condition", "negation"), "x16": ("condition", "negation"),
    "x17": ("temporal", "scope"), "x18": ("temporal", "scope"),
    "x19": ("actor", "exception"), "x20": ("actor", "exception"),
}

# ---------------------------------------------------------------------------
# Cohort 4: natural-language stress (12), unambiguous prose, §16.
# ---------------------------------------------------------------------------

_register("nl_stress", "nl_stress", "nl_stress", [
    ("nl01", "Radio spares live in the locked drawer, and that drawer is the duty operator's domain. "
             "Nobody else takes so much as a fuse from it. The one exception is the treasurer, "
             "who may raid it on club nights for the raffle microphone.",
     [_structure("PERMISSION", "ONLY_IF", [["action:take_spares_from_drawer"]],
                 ["actor:duty_operator", "actor:treasurer"], condition_mode="ANY")], ["actor:assistant"]),
    ("nl02", "The drying barn is a dust hazard while the malt turn is running, so power drills stay out of "
             "the bins for the whole turn. If a bin sensor needs fitting mid-turn, the maltster can "
             "authorize it, but only in writing.",
     [_structure("PROHIBITION", "IF", [["action:use_power_drills_in_bins"]], ["state:malt_turn_running"],
                 exceptions=["state:maltster_written_authorization"])], []),
    ("nl03", "Wardens who find a gate unlatched on the dawn round, and who cannot account for it in the "
             "movement book, must report it to the head office before their shift ends.",
     [_structure("REQUIREMENT", "IF", [["action:report_gate_to_head_office"]],
                 ["state:gate_unlatched_dawn_round", "!state:accounted_in_movement_book"], condition_mode="ALL")], []),
    ("nl04", "The annexe kitchen may be used by hirers once the caretaker has walked them through the "
             "shut-off valves (a five-minute routine, no appointment needed), and by nobody who has "
             "skipped that walkthrough.",
     [_structure("PERMISSION", "ONLY_IF", [["action:use_annexe_kitchen"]],
                 ["actor:hirer", "state:shutoff_walkthrough_done"], condition_mode="ALL")], ["actor:assistant"]),
    ("nl05", "It is open to any member who has held a full licence for two seasons to take the rescue boat "
             "out single-handed, weather card permitting.",
     [_structure("PERMISSION", "IF", [["action:take_rescue_boat_singlehanded"]],
                 ["actor:member_two_full_seasons", "state:weather_card_permitting"], condition_mode="ALL")],
     ["actor:assistant"]),
    ("nl06", "Lamps fitted by the visiting engineer, and still bearing her lead tag, may not be swapped "
             "out by the volunteer crew.",
     [_structure("PROHIBITION", "IF", [["action:swap_lamp"]],
                 ["state:lamp_fitted_by_visiting_engineer", "state:lamp_bears_lead_tag",
                  "actor:volunteer_crew"], condition_mode="ALL")], ["actor:assistant"]),
    ("nl07", "When the ringing is over, the tower door and the rope cupboard are locked up together with "
             "the sexton's key.",
     [_structure("REQUIREMENT", "IF", [["action:lock_tower_door", "action:lock_rope_cupboard"]],
                 ["event:ringing_over"], temporal="AFTER")], []),
    ("nl08", "The serving hatch opens at noon sharp for the lunch crowd. Hatch duty is the Saturday "
             "volunteers' alone, and they keep it even when the coordinator is away; the only time they "
             "stand down is a confirmed norovirus alert, when the paid staff take over.",
     [_structure("PERMISSION", "ONLY_IF", [["action:serve_hatch"]], ["actor:saturday_volunteer"],
                 exceptions=["state:norovirus_alert_confirmed"])], ["actor:assistant"]),
    ("nl09", "The treatment room runs on a two-bin system. Clinical waste waits in the yellow lobby for "
             "the contractor's van, and nothing from that lobby - no gloves, no wrappers, nothing - ever "
             "goes into the general skip at the back gate.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:put_yellow_lobby_waste_in_general_skip"]])], []),
    ("nl10", "Stock figures are a headache at the heritage railway shop, so here is the rule: the till "
             "roll totals and the float counts are copied across from the EPOS report, and that report is "
             "the only source the auditor accepts. Tote-board estimates and mental arithmetic do not count.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:till_roll_totals"], ["claim:float_counts"]],
                 ["evidence:epos_report"], regulated_kind="INFORMATION", provenance="TOOL_RESULT")], []),
    ("nl11", "Two faults will stop the press: the web-break sensor tripping, or the folder jamming past "
             "three sheets. Either one, and the printer on shift must kill the drive before leaving the cage.",
     [_structure("REQUIREMENT", "IF", [["action:kill_press_drive"]],
                 ["event:webbreak_sensor_tripped", "event:folder_jammed"], condition_mode="ANY")], []),
    ("nl12", "Strimming the cliff path is the warden's job alone (insurance, sadly), and only when the "
             "risk register shows the wind below force five.",
     [_structure("PERMISSION", "ONLY_IF", [["action:strim_cliff_path"]],
                 ["actor:warden", "state:wind_below_force_five"], condition_mode="ALL")], ["actor:assistant"]),
])

# ---------------------------------------------------------------------------
# Cohort 5: ambiguity controls (8), §17: both readings carry positive
# linguistic support; explicit coordination is NOT ambiguity.
# ---------------------------------------------------------------------------

_register("ambiguity", "ambiguity", "controlled", [
    ("am01", "The say on campsite layout belongs to the site steward.",
     [_structure("PERMISSION", "IF", [["action:decide_campsite_layout"]], ["actor:site_steward"]),
      _structure("PERMISSION", "ONLY_IF", [["action:decide_campsite_layout"]], ["actor:site_steward"])],
     ["actor:assistant"]),
    ("am02", "Signing off the muster sheet is a matter for the trek leader.",
     [_structure("PERMISSION", "IF", [["action:signoff_muster_sheet"]], ["actor:trek_leader"]),
      _structure("PERMISSION", "ONLY_IF", [["action:signoff_muster_sheet"]], ["actor:trek_leader"])],
     ["actor:assistant"]),
    ("am03", "Photocopying the exhibit licence and the franking stamp is not authorised.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:photocopy_exhibit_licence", "action:photocopy_franking_stamp"]]),
      _structure("PROHIBITION", "UNCONDITIONAL", [["action:photocopy_exhibit_licence"], ["action:photocopy_franking_stamp"]])], []),
    ("am04", "The route card and the telematics dump may not be copied.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:copy_route_card", "action:copy_telematics_dump"]]),
      _structure("PROHIBITION", "UNCONDITIONAL", [["action:copy_route_card"], ["action:copy_telematics_dump"]])], []),
    ("am05", "No cream may be whipped without the pasteurisation log being initialled.",
     [_structure("PROHIBITION", "UNLESS", [["action:whip_cream"]], exceptions=["state:pasteurisation_log_initialled"]),
      _structure("PROHIBITION", "IF", [["action:whip_cream"]], ["!state:pasteurisation_log_initialled"])], []),
    ("am06", "No seed potatoes leave the store without the inspector's chalk mark.",
     [_structure("PROHIBITION", "UNLESS", [["action:remove_seed_potatoes_from_store"]], exceptions=["state:inspector_chalk_mark_present"]),
      _structure("PROHIBITION", "IF", [["action:remove_seed_potatoes_from_store"]], ["!state:inspector_chalk_mark_present"])], []),
    ("am07", "The new bandstand may not be booked until the safety certificate is framed at the lodge.",
     [_structure("PROHIBITION", "UNLESS", [["action:book_new_bandstand"]], exceptions=["state:safety_certificate_framed"]),
      _structure("PROHIBITION", "IF", [["action:book_new_bandstand"]], ["!state:safety_certificate_framed"])], []),
    ("am08", "Sponsorship slides may not run on the scoreboard until the league has signed the media deal.",
     [_structure("PROHIBITION", "UNLESS", [["action:run_sponsorship_slides"]], exceptions=["state:league_signed_media_deal"]),
      _structure("PROHIBITION", "IF", [["action:run_sponsorship_slides"]], ["!state:league_signed_media_deal"])], []),
])


# --------------------------------------------------------------------- build

def _positive_atoms(structure: dict) -> set:
    atoms = set()
    for clause in structure["target_clauses"]:
        for literal in clause:
            atoms.add(literal[1:] if literal.startswith("!") else literal)
    for name in ("condition_literals", "exception_literals"):
        for literal in structure[name]:
            atoms.add(literal[1:] if literal.startswith("!") else literal)
    return atoms


COHORT_PLAN = {"simple": 20, "structural": 20, "multi_clause": 20,
               "nl_stress": 12, "ambiguity": 8}
FAMILY_PLAN = {"simple": 20, "modality": 3, "condition": 2, "exception": 3, "negation": 3,
               "scope": 2, "actor": 2, "identity": 1, "provenance": 1, "cardinality": 1,
               "temporal": 2, "multi_axis": 20, "nl_stress": 12, "ambiguity": 8}


def build_phv1_holdout() -> list[PolicyPHV1Case]:
    """Build the frozen PHV1 holdout corpus deterministically (80 cases)."""
    cases: list[PolicyPHV1Case] = []
    for cohort, family, style, entries, trap, axes in PHV1_TEMPLATES:
        for entry in entries:
            key, text, structures, extra_atoms = entry
            structures = [dict(structure) for structure in structures]
            atoms = set()
            for structure in structures:
                atoms.update(_positive_atoms(structure))
            atoms.update(extra_atoms)
            distractor = f"distractor:{key}"
            atom_catalog = tuple(sorted(atoms | {distractor}))
            programs = [compile_v3_structure(structure) for structure in structures]
            ambiguous = len(structures) > 1
            if trap and ambiguous:
                raise ValueError(f"trap families must be unambiguous: {family}::{key}")
            if not ambiguous and len(structures) != 1:
                raise ValueError(f"unambiguous case needs exactly one reading: {family}::{key}")
            if ambiguous:
                for program in programs[1:]:
                    if _distinguishing_world(programs[0], program, list(atom_catalog)) is None:
                        raise ValueError(f"ambiguous case {family}::{key} readings are not "
                                         "behaviorally distinct")
            worlds = generate_worlds(programs[0], list(atom_catalog))
            if ambiguous:
                pair = _distinguishing_world(programs[0], programs[1], list(atom_catalog))
                if pair:
                    facts, expected_a, expected_b = pair
                    worlds.append({"facts": facts, "expected": expected_a,
                                   "alternative_expected": expected_b,
                                   "distinguishes": "distinguishes_admissible_readings"})
            case = PolicyPHV1Case(
                case_id=f"{family}::{key}", cohort=cohort, family=family, style=style,
                policy=text, atom_catalog=atom_catalog, ambiguous=ambiguous, trap=trap,
                admissible_structures=tuple(structures),
                admissible_programs=tuple({json.dumps(p, sort_keys=True): p for p in programs}.values()),
                worlds=tuple(worlds),
                axes=MULTI_AXIS_AXES.get(key, ()))
            cases.append(case)
    observed_cohorts = {}
    observed_families = {}
    for case in cases:
        observed_cohorts[case.cohort] = observed_cohorts.get(case.cohort, 0) + 1
        observed_families[case.family] = observed_families.get(case.family, 0) + 1
    if observed_cohorts != COHORT_PLAN:
        raise ValueError(f"cohort composition mismatch: {observed_cohorts}")
    if observed_families != FAMILY_PLAN:
        raise ValueError(f"family composition mismatch: {observed_families}")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("duplicate case ids")
    for case in cases:
        if case.family == "multi_axis" and len(case.axes) < 2:
            raise ValueError(f"multi-axis case needs >= 2 axes: {case.case_id}")
    return sorted(cases, key=lambda case: case.case_id)


def benchmark_phv1_document(cases: list[PolicyPHV1Case]) -> dict:
    rows = [case.as_dict() for case in cases]
    return {"schema_version": "guardian-vnext-policy-phv1-holdout-v1",
            "prereg": "docs/vnext/PHV1_PREREG_GATES_V1.json",
            "frozen_before_predictions": True,
            "annotation_basis": "CONSTRUCTION_FROM_TEMPLATES_NOT_MODEL_LABELS",
            "cohorts": dict(COHORT_PLAN), "families": dict(FAMILY_PLAN),
            "styles": ["controlled", "nl_stress"],
            "cases_sha256": digest(rows), "cases": rows}

"""Policy v5 controlled benchmark: 142 cases, gold by construction.

V5 isolates MUTATION ADMISSION CONTROL. The set is engineered so that the
mutation catalog always proposes locally plausible alternatives; the open
question is which proposals are textually licensed. Three case classes:

1. Designated positive-support traps (62 unambiguous): the text licenses
   exactly one reading, and a catalog mutation of that reading is
   non-contradicting, uses the same words, sounds plausible, but is NOT
   entailed (necessity/sufficiency flips, "X may" -> "only X may",
   conjunction/disjunction flips, exception coordination flips, together/
   separate scope flips, exception polarity flips).
2. Genuinely ambiguous cases (48, controlled plus natural prose): both
   behavioral readings carry textual support, and every pair is bridged by
   exactly one catalog mutation (no unreachable ceiling probes in v5: the
   open question is admission, not reachability).
3. Replication and natural-language stress cases (58 unambiguous controlled +
   36 unambiguous prose + 20 ambiguous prose): fresh entities and fresh
   phrasings of the v4 phenomena (indirect permission wording, multi-sentence
   rules, nested relative clauses, provenance, cardinality, not-both).

Gold design notes. Bare "X may A" grants permission to X and stays silent
about everyone else: under the v5 hypothesis (positive entailment required
for admission) the exclusive reading "only X may A" is a trap, so bare-actor
sentences are unambiguous here with the descriptive (IF) reading as gold;
the two actor cases with genuine restrictive-versus-descriptive tension
("permission rests with ...") carry both readings. Scope-attachment
ambiguity is operationalized as the expressible together/separate flip.

Gold is compiled deterministically from typed structures and frozen before
any candidate request; models never see labels.
"""

from dataclasses import dataclass
import json
import random

from .integrity import digest
from .policy_v3_benchmark import (
    compile_v3_structure, evaluate_v3_program, generate_worlds, _distinguishing_world)


@dataclass(frozen=True)
class PolicyV5Case:
    case_id: str
    family: str
    style: str
    policy: str
    atom_catalog: tuple
    ambiguous: bool
    trap: bool
    admissible_structures: tuple
    admissible_programs: tuple
    worlds: tuple

    def as_dict(self) -> dict:
        return {"case_id": self.case_id, "family": self.family, "style": self.style,
                "policy": self.policy, "atom_catalog": list(self.atom_catalog),
                "ambiguous": self.ambiguous, "trap": self.trap,
                "admissible_structures": [dict(s) for s in self.admissible_structures],
                "admissible_programs": [dict(p) for p in self.admissible_programs],
                "worlds": [dict(w) for w in self.worlds]}


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
V5_TEMPLATES: list[tuple] = []


def _register(family, style, cases, trap=False):
    V5_TEMPLATES.append((family, style, cases, trap))


# ---------------------------------------------------------------------------
# Controlled unambiguous set (56): 36 designated traps + 20 replication.
# ---------------------------------------------------------------------------

_register("trap_relation", "controlled", [
    ("tr1", "You may renew the berth licence only while the marina office is open.",
     [_structure("PERMISSION", "ONLY_IF", [["action:renew_berth_licence"]], ["state:marina_office_open"])], []),
    ("tr2", "A guest pass may be printed only if the climbing waiver is on file.",
     [_structure("PERMISSION", "ONLY_IF", [["action:print_guest_pass"]], ["state:climbing_waiver_on_file"])], []),
    ("tr3", "The incubator door may be opened only after the humidity cycle has finished.",
     [_structure("PERMISSION", "ONLY_IF", [["action:open_incubator_door"]], ["event:humidity_cycle_finished"], temporal="AFTER")], []),
    ("tr4", "Overtime may be authorized only when a severity-two incident is active.",
     [_structure("PERMISSION", "ONLY_IF", [["action:authorize_overtime"]], ["state:severity_two_incident_active"])], []),
    ("tr5", "The kiln may be opened only while the cooldown indicator is green.",
     [_structure("PERMISSION", "ONLY_IF", [["action:open_kiln"]], ["state:cooldown_indicator_green"])], []),
    ("tr6", "Retake slots may be booked only after the coaching module is complete.",
     [_structure("PERMISSION", "ONLY_IF", [["action:book_retake_slot"]], ["event:coaching_module_complete"], temporal="AFTER")], []),
    ("tr7", "Members may extend the tool loan only if no hold is pending on the item.",
     [_structure("PERMISSION", "ONLY_IF", [["action:extend_tool_loan"]], ["!state:hold_pending"])], []),
    ("tr8", "The sampling port may be unlocked only where the quarantine flag has been cleared.",
     [_structure("PERMISSION", "ONLY_IF", [["action:unlock_sampling_port"]], ["state:quarantine_flag_cleared"])], []),
    ("tr9", "If the calibration certificate is current, you may sign the test report.",
     [_structure("PERMISSION", "IF", [["action:sign_test_report"]], ["state:calibration_certificate_current"])], []),
    ("tr10", "If the escort holds a visitor badge, the delivery van may enter the loading dock.",
     [_structure("PERMISSION", "IF", [["action:enter_loading_dock"]], ["state:escort_visitor_badge_held"])], []),
    ("tr11", "If the pool log shows balanced chemicals, the swim lane may be opened.",
     [_structure("PERMISSION", "IF", [["action:open_swim_lane"]], ["state:pool_log_balanced"])], []),
    ("tr12", "Where the pilot has filed the flight notification, the balloon launch may proceed.",
     [_structure("PERMISSION", "IF", [["action:launch_balloon"]], ["state:flight_notification_filed"])], []),
], trap=True)

_register("trap_and_or", "controlled", [
    ("to1", "Authorize the payout only after the auditor and the trustee have both countersigned.",
     [_structure("PERMISSION", "ONLY_IF", [["action:authorize_payout"]], ["state:auditor_countersigned", "state:trustee_countersigned"], condition_mode="ALL")], []),
    ("to2", "The specimen may leave the lab only if the chain-of-custody form and the courier manifest are complete.",
     [_structure("PERMISSION", "ONLY_IF", [["action:leave_specimen_lab"]], ["state:custody_form_complete", "state:courier_manifest_complete"], condition_mode="ALL")], []),
    ("to3", "You may book the observatory night only when the weather briefing and the dome inspection are both cleared.",
     [_structure("PERMISSION", "ONLY_IF", [["action:book_observatory_night"]], ["state:weather_briefing_cleared", "state:dome_inspection_cleared"], condition_mode="ALL")], []),
    ("to4", "The grant may be drawn down only if the compliance report and the budget variance note are filed.",
     [_structure("PERMISSION", "ONLY_IF", [["action:draw_down_grant"]], ["state:compliance_report_filed", "state:budget_variance_note_filed"], condition_mode="ALL")], []),
    ("to5", "If the fire alarm or the gas detector sounds, abandon the level immediately.",
     [_structure("REQUIREMENT", "IF", [["action:abandon_level"]], ["event:fire_alarm_sounded", "event:gas_detector_sounded"], condition_mode="ANY")], []),
    ("to6", "If the feeder jams or the temperature probe drifts, restart the roasting line.",
     [_structure("REQUIREMENT", "IF", [["action:restart_roasting_line"]], ["event:feeder_jammed", "event:temp_probe_drifted"], condition_mode="ANY")], []),
    ("to7", "If either the gate agent or the ramp lead reports a mismatch, hold the flight.",
     [_structure("REQUIREMENT", "IF", [["action:hold_flight"]], ["state:gate_agent_mismatch", "state:ramp_lead_mismatch"], condition_mode="ANY")], []),
    ("to8", "If the tide gauge or the wind sensor flags a limit, suspend the ferry crossing.",
     [_structure("REQUIREMENT", "IF", [["action:suspend_ferry_crossing"]], ["state:tide_gauge_limit", "state:wind_sensor_limit"], condition_mode="ANY")], []),
], trap=True)

_register("trap_exception", "controlled", [
    ("te1", "Do not waive the restocking fee unless the item arrived damaged or the order was duplicated.",
     [_structure("PROHIBITION", "UNLESS", [["action:waive_restocking_fee"]], exceptions=["state:item_arrived_damaged", "state:order_duplicated"], exception_mode="ANY")], []),
    ("te2", "The seal stays on the specimen unless the lab director or the deputy director authorizes removal.",
     [_structure("PROHIBITION", "UNLESS", [["action:remove_specimen_seal"]], exceptions=["state:lab_director_authorized", "state:deputy_director_authorized"], exception_mode="ANY")], []),
    ("te3", "Do not release the escrow unless both the buyer's agent and the seller's agent have confirmed.",
     [_structure("PROHIBITION", "UNLESS", [["action:release_escrow"]], exceptions=["state:buyers_agent_confirmed", "state:sellers_agent_confirmed"], exception_mode="ALL")], []),
    ("te4", "The exhibit may not travel unless the conservator and the registrar both approve.",
     [_structure("PROHIBITION", "UNLESS", [["action:travel_exhibit"]], exceptions=["state:conservator_approved", "state:registrar_approved"], exception_mode="ALL")], []),
    ("te5", "Do not purge the tape backup unless the retention clock has expired.",
     [_structure("PROHIBITION", "UNLESS", [["action:purge_tape_backup"]], exceptions=["state:retention_clock_expired"])], []),
    ("te6", "Keep the batch on hold unless the microbiology panel comes back clear.",
     [_structure("PROHIBITION", "UNLESS", [["action:release_batch_from_hold"]], exceptions=["!state:microbiology_panel_contaminated"])], []),
], trap=True)

_register("trap_scope", "controlled", [
    ("ts1", "Do not close the intake form and the consent form in the same batch.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:close_intake_form", "action:close_consent_form"]])], []),
    ("ts2", "Disclosing the pricing memo and the vendor list in one meeting is prohibited.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:disclose_pricing_memo", "action:disclose_vendor_list"]])], []),
    ("ts3", "Merging the general ledger and the payroll ledger in a single export is forbidden.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:merge_general_ledger", "action:merge_payroll_ledger"]])], []),
    ("ts4", "Cancelling both the crane booking and the rigging booking on one ticket is barred.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:cancel_crane_booking", "action:cancel_rigging_booking"]])], []),
], trap=True)

_register("trap_actor", "controlled", [
    ("ta1", "Shift supervisors may authorize a comp meal.",
     [_structure("PERMISSION", "IF", [["action:authorize_comp_meal"]], ["actor:shift_supervisor"])], ["actor:assistant"]),
    ("ta2", "The observatory director may close the dome early.",
     [_structure("PERMISSION", "IF", [["action:close_dome_early"]], ["actor:observatory_director"])], ["actor:assistant"]),
    ("ta3", "Duty pharmacists may draw from the reserve stock.",
     [_structure("PERMISSION", "IF", [["action:draw_reserve_stock"]], ["actor:duty_pharmacist"])], ["actor:assistant"]),
    ("ta4", "Only the radiation safety officer may reset the dosimeter badges.",
     [_structure("PERMISSION", "ONLY_IF", [["action:reset_dosimeter_badges"]], ["actor:radiation_safety_officer"])], ["actor:assistant"]),
    ("ta5", "Only the head zookeeper may authorize the enrichment feed.",
     [_structure("PERMISSION", "ONLY_IF", [["action:authorize_enrichment_feed"]], ["actor:head_zookeeper"])], ["actor:assistant"]),
    ("ta6", "Only the duty engineer may bypass the interlock.",
     [_structure("PERMISSION", "ONLY_IF", [["action:bypass_interlock"]], ["actor:duty_engineer"])], ["actor:assistant"]),
], trap=True)

_register("replication_direction", "controlled", [
    ("rd1", "The certificate may be reissued if and only if the continuing-education credits are recorded.",
     [_structure("PERMISSION", "IF_AND_ONLY_IF", [["action:reissue_certificate"]], ["state:ce_credits_recorded"])], []),
    ("rd2", "If the duplicate key is logged, the locksmith may cut a replacement.",
     [_structure("PERMISSION", "IF", [["action:cut_replacement_key"]], ["state:duplicate_key_logged"])], []),
    ("rd3", "The engine test cell may be run only when the exhaust scrubber is active.",
     [_structure("PERMISSION", "ONLY_IF", [["action:run_engine_test_cell"]], ["state:exhaust_scrubber_active"])], []),
    ("rd4", "Do not exceed the sound curfew unless the festival committee grants an extension.",
     [_structure("PROHIBITION", "UNLESS", [["action:exceed_sound_curfew"]], exceptions=["state:festival_extension_granted"])], []),
])

_register("replication_condition_stack", "controlled", [
    ("rs1", "The climb may proceed only if the route is flagged open and the weather window is green.",
     [_structure("PERMISSION", "ONLY_IF", [["action:proceed_climb"]], ["state:route_flagged_open", "state:weather_window_green"], condition_mode="ALL")], []),
    ("rs2", "Do not start the pour unless the formwork passed inspection and the batch ticket matches.",
     [_structure("PROHIBITION", "UNLESS", [["action:start_pour"]], exceptions=["state:formwork_inspected", "state:batch_ticket_matched"], exception_mode="ALL")], []),
])

_register("replication_nested_qualifier", "controlled", [
    ("rn1", "Requests that cite the archive case number may be expedited by the records clerk.",
     [_structure("PERMISSION", "IF", [["action:expedite_request"]], ["state:archive_case_number_cited"])], []),
    ("rn2", "Entries that list a co-author and that lack the ethics clearance may not be submitted.",
     [_structure("PROHIBITION", "IF", [["action:submit_entry"]], ["state:coauthor_listed", "!state:ethics_clearance_present"], condition_mode="ALL")], []),
])

_register("replication_provenance", "controlled", [
    ("rp1", "The tonnage figure must be read from the weighbridge ticket alone.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:tonnage_figure"]], ["evidence:weighbridge_ticket"], regulated_kind="INFORMATION", provenance="TOOL_RESULT")], []),
    ("rp2", "Report the outage count exactly as the network monitor states it.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:outage_count"]], ["evidence:network_monitor_state"], regulated_kind="INFORMATION", provenance="TOOL_RESULT")], []),
])

_register("replication_cardinality", "controlled", [
    ("rc1", "At most three sample reruns are allowed per assay.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["state:reruns_gt_3"]], quantification="AT_MOST_3", regulated_kind="STATE")], []),
    ("rc2", "At most one name change is honored per season.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["state:name_changes_gt_1"]], quantification="AT_MOST_1_PER_TURN", regulated_kind="STATE")], []),
])

_register("replication_not_both", "controlled", [
    ("rb1", "Issue the badge either as a sticker or as a card — never both for one visitor.",
     [_structure("PROHIBITION", "AND_NOT_EACH", [["claim:sticker_badge_issued", "claim:card_badge_issued"]], quantification="NOT_BOTH")], []),
    ("rb2", "The settlement is paid by wire or by voucher, never by both on one account.",
     [_structure("PROHIBITION", "AND_NOT_EACH", [["claim:wire_paid", "claim:voucher_paid"]], quantification="NOT_BOTH")], []),
])

_register("replication_state_action", "controlled", [
    ("rm1", "The wash log must show the drum count.",
     [_structure("REQUIREMENT", "UNCONDITIONAL", [["state:wash_log_shows_drum_count"]])], []),
    ("rm2", "The dive log must record the bottom time.",
     [_structure("REQUIREMENT", "UNCONDITIONAL", [["state:dive_log_records_bottom_time"]])], []),
])

_register("replication_identity", "controlled", [
    ("ri1", "A student may withdraw their own application only.",
     [_structure("PERMISSION", "ONLY_IF", [["action:withdraw_application"]], ["identity:applicant_self"])], []),
    ("ri2", "The pilot who filed the flight plan may cancel it, no one else.",
     [_structure("PERMISSION", "ONLY_IF", [["action:cancel_flight_plan"]], ["identity:filing_pilot"])], []),
])

_register("replication_temporal", "controlled", [
    ("rt1", "The night override may be granted only after the load forecast is published.",
     [_structure("PERMISSION", "ONLY_IF", [["action:grant_night_override"]], ["event:load_forecast_published"], temporal="AFTER")], []),
])

_register("replication_distractor_permission", "controlled", [
    ("rdp1", "Failure to obtain the export licence blocks the shipment; the file may not proceed in any form.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:proceed_shipment_file"]])], []),
])

_register("replication_unconditional", "controlled", [
    ("ru1", "The interlock key is never to leave the control room.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:remove_interlock_key"]])], []),
    ("ru2", "Always initial the control sheet before the shift change.",
     [_structure("REQUIREMENT", "UNCONDITIONAL", [["state:control_sheet_initialed"]])], []),
])

# ---------------------------------------------------------------------------
# Controlled ambiguous set (28): two behaviorally distinct admissible
# readings each, every pair bridged by one catalog mutation.
# ---------------------------------------------------------------------------

_register("ambiguous_if_onlyif", "controlled", [
    ("am1", "Divers with a logged checkout may borrow the camera housing.",
     [_structure("PERMISSION", "IF", [["action:borrow_camera_housing"]], ["state:checkout_logged"]),
      _structure("PERMISSION", "ONLY_IF", [["action:borrow_camera_housing"]], ["state:checkout_logged"])], []),
    ("am2", "Renters whose damage deposit is held may park in the covered bay.",
     [_structure("PERMISSION", "IF", [["action:park_covered_bay"]], ["state:damage_deposit_held"]),
      _structure("PERMISSION", "ONLY_IF", [["action:park_covered_bay"]], ["state:damage_deposit_held"])], []),
    ("am3", "Teams holding a valid range card may book the long lane.",
     [_structure("PERMISSION", "IF", [["action:book_long_lane"]], ["state:range_card_valid"]),
      _structure("PERMISSION", "ONLY_IF", [["action:book_long_lane"]], ["state:range_card_valid"])], []),
    ("am4", "Handlers with a current rabies certificate may use the agility ring.",
     [_structure("PERMISSION", "IF", [["action:use_agility_ring"]], ["state:rabies_certificate_current"]),
      _structure("PERMISSION", "ONLY_IF", [["action:use_agility_ring"]], ["state:rabies_certificate_current"])], []),
    ("am5", "Researchers listed on the protocol may access the sample freezer.",
     [_structure("PERMISSION", "IF", [["action:access_sample_freezer"]], ["state:researcher_on_protocol"]),
      _structure("PERMISSION", "ONLY_IF", [["action:access_sample_freezer"]], ["state:researcher_on_protocol"])], []),
    ("am6", "Vendors holding a prepaid permit may occupy the market stall.",
     [_structure("PERMISSION", "IF", [["action:occupy_market_stall"]], ["state:prepaid_permit_held"]),
      _structure("PERMISSION", "ONLY_IF", [["action:occupy_market_stall"]], ["state:prepaid_permit_held"])], []),
    ("am7", "Members with an access fob may enter the boathouse.",
     [_structure("PERMISSION", "IF", [["action:enter_boathouse"]], ["state:access_fob_held"]),
      _structure("PERMISSION", "ONLY_IF", [["action:enter_boathouse"]], ["state:access_fob_held"])], []),
    ("am8", "Clients whose intake form is on file may schedule the float tank.",
     [_structure("PERMISSION", "IF", [["action:schedule_float_tank"]], ["state:intake_form_on_file"]),
      _structure("PERMISSION", "ONLY_IF", [["action:schedule_float_tank"]], ["state:intake_form_on_file"])], []),
])

_register("ambiguous_and_or", "controlled", [
    ("ao1", "Do not start the shift if the crew list is stale or the sign-in sheet is missing.",
     [_structure("PROHIBITION", "IF", [["action:start_shift"]], ["state:crew_list_stale", "state:signin_sheet_missing"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:start_shift"]], ["state:crew_list_stale", "state:signin_sheet_missing"], condition_mode="ALL")], []),
    ("ao2", "Do not accept the pallet if the seal number differs or the manifest page is torn.",
     [_structure("PROHIBITION", "IF", [["action:accept_pallet"]], ["state:seal_number_differs", "state:manifest_page_torn"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:accept_pallet"]], ["state:seal_number_differs", "state:manifest_page_torn"], condition_mode="ALL")], []),
    ("ao3", "Do not light the kiln if the gas certificate has lapsed or the vent check failed.",
     [_structure("PROHIBITION", "IF", [["action:light_kiln"]], ["state:gas_certificate_lapsed", "state:vent_check_failed"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:light_kiln"]], ["state:gas_certificate_lapsed", "state:vent_check_failed"], condition_mode="ALL")], []),
    ("ao4", "Do not seat the group if the deposit is unpaid or the headcount is unconfirmed.",
     [_structure("PROHIBITION", "IF", [["action:seat_group"]], ["state:deposit_unpaid", "state:headcount_unconfirmed"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:seat_group"]], ["state:deposit_unpaid", "state:headcount_unconfirmed"], condition_mode="ALL")], []),
    ("ao5", "Do not power the stage if the cable inspection is overdue or the ground-fault trip is untested.",
     [_structure("PROHIBITION", "IF", [["action:power_stage"]], ["state:cable_inspection_overdue", "state:groundfault_trip_untested"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:power_stage"]], ["state:cable_inspection_overdue", "state:groundfault_trip_untested"], condition_mode="ALL")], []),
    ("ao6", "Do not dispense if the prescription is expired or the allergy flag is raised.",
     [_structure("PROHIBITION", "IF", [["action:dispense_medication"]], ["state:prescription_expired", "state:allergy_flag_raised"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:dispense_medication"]], ["state:prescription_expired", "state:allergy_flag_raised"], condition_mode="ALL")], []),
])

_register("ambiguous_exception_mode", "controlled", [
    ("ax1", "Do not reveal the bid total unless the procurement officer or the auction clerk approves.",
     [_structure("PROHIBITION", "UNLESS", [["action:reveal_bid_total"]], exceptions=["state:procurement_officer_approves", "state:auction_clerk_approves"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:reveal_bid_total"]], exceptions=["state:procurement_officer_approves", "state:auction_clerk_approves"], exception_mode="ALL")], []),
    ("ax2", "The tasting bar stays closed unless the head brewer or the floor manager unlocks it.",
     [_structure("PROHIBITION", "UNLESS", [["action:open_tasting_bar"]], exceptions=["state:head_brewer_unlocks", "state:floor_manager_unlocks"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:open_tasting_bar"]], exceptions=["state:head_brewer_unlocks", "state:floor_manager_unlocks"], exception_mode="ALL")], []),
    ("ax3", "Do not archive the logbook unless the archive committee or the records officer signs off.",
     [_structure("PROHIBITION", "UNLESS", [["action:archive_logbook"]], exceptions=["state:archive_committee_signs", "state:records_officer_signs"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:archive_logbook"]], exceptions=["state:archive_committee_signs", "state:records_officer_signs"], exception_mode="ALL")], []),
    ("ax4", "Never board the whale-watch deck unless the skipper or the first mate clears the sea state.",
     [_structure("PROHIBITION", "UNLESS", [["action:board_whalewatch_deck"]], exceptions=["state:skipper_clears", "state:first_mate_clears"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:board_whalewatch_deck"]], exceptions=["state:skipper_clears", "state:first_mate_clears"], exception_mode="ALL")], []),
    ("ax5", "Do not unlock the specimen drawer unless the curator or the preparator logs the request.",
     [_structure("PROHIBITION", "UNLESS", [["action:unlock_specimen_drawer"]], exceptions=["state:curator_logs_request", "state:preparator_logs_request"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:unlock_specimen_drawer"]], exceptions=["state:curator_logs_request", "state:preparator_logs_request"], exception_mode="ALL")], []),
])

_register("ambiguous_temporal", "controlled", [
    ("at1", "You may trim the hedge before the nesting survey begins.",
     [_structure("PERMISSION", "IF", [["action:trim_hedge"]], ["!event:nesting_survey_begun"], temporal="BEFORE"),
      _structure("PERMISSION", "ONLY_IF", [["action:trim_hedge"]], ["!event:nesting_survey_begun"], temporal="BEFORE")], []),
    ("at2", "The slip may be reassigned once the waitlist closes.",
     [_structure("PERMISSION", "IF", [["action:reassign_slip"]], ["event:waitlist_closed"], temporal="AFTER"),
      _structure("PERMISSION", "ONLY_IF", [["action:reassign_slip"]], ["event:waitlist_closed"], temporal="AFTER")], []),
    ("at3", "The skid trail may be reopened after the geotech report lands.",
     [_structure("PERMISSION", "IF", [["action:reopen_skid_trail"]], ["event:geotech_report_landed"], temporal="AFTER"),
      _structure("PERMISSION", "ONLY_IF", [["action:reopen_skid_trail"]], ["event:geotech_report_landed"], temporal="AFTER")], []),
])

_register("ambiguous_scope", "controlled", [
    ("asc1", "Do not cancel the mooring booking and the haul-out booking.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:cancel_mooring_booking", "action:cancel_haulout_booking"]]),
      _structure("PROHIBITION", "UNCONDITIONAL", [["action:cancel_mooring_booking"], ["action:cancel_haulout_booking"]])], []),
    ("asc2", "Do not laminate the certificate and the appendix.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:laminate_certificate", "action:laminate_appendix"]]),
      _structure("PROHIBITION", "UNCONDITIONAL", [["action:laminate_certificate"], ["action:laminate_appendix"]])], []),
    ("asc3", "Do not mute the stage channel and the house channel.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:mute_stage_channel", "action:mute_house_channel"]]),
      _structure("PROHIBITION", "UNCONDITIONAL", [["action:mute_stage_channel"], ["action:mute_house_channel"]])], []),
    ("asc4", "Do not veto the flavor batch and the label proof.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:veto_flavor_batch", "action:veto_label_proof"]]),
      _structure("PROHIBITION", "UNCONDITIONAL", [["action:veto_flavor_batch"], ["action:veto_label_proof"]])], []),
])

_register("ambiguous_actor_exclusive", "controlled", [
    ("aae1", "Permission to recalibrate the scale rests with the duty technician.",
     [_structure("PERMISSION", "IF", [["action:recalibrate_scale"]], ["actor:duty_technician"]),
      _structure("PERMISSION", "ONLY_IF", [["action:recalibrate_scale"]], ["actor:duty_technician"])], ["actor:assistant"]),
    ("aae2", "Authority to release the tender sits with the harbor launch master.",
     [_structure("PERMISSION", "IF", [["action:release_tender"]], ["actor:harbor_launch_master"]),
      _structure("PERMISSION", "ONLY_IF", [["action:release_tender"]], ["actor:harbor_launch_master"])], ["actor:assistant"]),
])

# ---------------------------------------------------------------------------
# Natural-language stress set, unambiguous (36): independently authored
# prose with embedded positive-support traps and v4 replication phenomena.
# ---------------------------------------------------------------------------

_register("stress_trap_relation", "nl_stress", [
    ("str1", "Deactivation of the alarm zone is reserved to the period when the fire marshal is on site.",
     [_structure("PERMISSION", "ONLY_IF", [["action:deactivate_alarm_zone"]], ["state:fire_marshal_on_site"])], []),
    ("str2", "Approval of the color change is conditioned solely on the brand board's written nod.",
     [_structure("PERMISSION", "ONLY_IF", [["action:approve_color_change"]], ["state:brand_board_written_nod"])], []),
    ("str3", "The sole circumstance under which a comp day may be cashed out is a declared staffing emergency.",
     [_structure("PERMISSION", "ONLY_IF", [["action:cash_out_comp_day"]], ["state:staffing_emergency_declared"])], []),
    ("str4", "Reprinting the lost badge is available exclusively where the holder presents a photo ID.",
     [_structure("PERMISSION", "ONLY_IF", [["action:reprint_lost_badge"]], ["state:photo_id_presented"])], []),
    ("str5", "Wherever the pasteurizer logs a clean cycle, the vat may be opened for sampling.",
     [_structure("PERMISSION", "IF", [["action:open_vat_for_sampling"]], ["state:pasteurizer_clean_cycle"])], []),
    ("str6", "Any courier holding a dock card is entitled to use the freight elevator.",
     [_structure("PERMISSION", "IF", [["action:use_freight_elevator"]], ["state:dock_card_held"])], []),
    ("str7", "Once the calibration sticker is renewed, the gauge cart may circulate on the floor.",
     [_structure("PERMISSION", "IF", [["action:circulate_gauge_cart"]], ["event:calibration_sticker_renewed"], temporal="AFTER")], []),
    ("str8", "Overtime beyond the roster cap is permitted only in the week a severity call is open.",
     [_structure("PERMISSION", "ONLY_IF", [["action:approve_overtime_beyond_cap"]], ["state:severity_call_open"])], []),
], trap=True)

_register("stress_trap_and_or", "nl_stress", [
    ("sto1", "The lender will consider the hardship plan only when both the income statement and the affidavit are in the file.",
     [_structure("PERMISSION", "ONLY_IF", [["action:consider_hardship_plan"]], ["state:income_statement_file", "state:affidavit_file"], condition_mode="ALL")], []),
    ("sto2", "The pit gate opens for the tire crew only after the fueling team and the scrutineers have both cleared the lane.",
     [_structure("PERMISSION", "ONLY_IF", [["action:open_pit_gate"]], ["event:fueling_team_cleared", "event:scrutineers_cleared"], condition_mode="ALL")], []),
    ("sto3", "If either the chiller or the air handler trips, restart the batch line from the top.",
     [_structure("REQUIREMENT", "IF", [["action:restart_batch_line"]], ["event:chiller_tripped", "event:air_handler_tripped"], condition_mode="ANY")], []),
    ("sto4", "Where the motion sensor or the glass-break detector triggers, log the event in the night book.",
     [_structure("REQUIREMENT", "IF", [["action:log_night_book_entry"]], ["event:motion_sensor_triggered", "event:glass_break_triggered"], condition_mode="ANY")], []),
    ("sto5", "Either a falling barometer or an ice report is enough to ground the balloon.",
     [_structure("REQUIREMENT", "IF", [["action:ground_balloon"]], ["state:falling_barometer", "state:ice_report"], condition_mode="ANY")], []),
], trap=True)

_register("stress_trap_exception", "nl_stress", [
    ("ste1", "Late penalty waivers stay off the table unless the billing desk documents a hardship or the account carries a credit.",
     [_structure("PROHIBITION", "UNLESS", [["action:waive_late_penalty"]], exceptions=["state:hardship_documented", "state:account_credit"], exception_mode="ANY")], []),
    ("ste2", "The hatch seal is not to be broken unless both the shift lead and the quality officer have logged their consent.",
     [_structure("PROHIBITION", "UNLESS", [["action:break_hatch_seal"]], exceptions=["state:shift_lead_logged", "state:quality_officer_logged"], exception_mode="ALL")], []),
    ("ste3", "Do not extend the bakery's credit line unless the co-op board or the treasurer renews the guarantee.",
     [_structure("PROHIBITION", "UNLESS", [["action:extend_credit_line"]], exceptions=["state:board_renewed", "state:treasurer_renewed"], exception_mode="ANY")], []),
    ("ste4", "Do not purge the visitor logs unless the privacy officer or the retention officer countersigns the purge list.",
     [_structure("PROHIBITION", "UNLESS", [["action:purge_visitor_logs"]], exceptions=["state:privacy_officer_countersigned", "state:retention_officer_countersigned"], exception_mode="ANY")], []),
    ("ste5", "The cage stays locked unless the animal handler or the attending vet is present.",
     [_structure("PROHIBITION", "UNLESS", [["action:unlock_cage"]], exceptions=["state:animal_handler_present", "state:attending_vet_present"], exception_mode="ANY")], []),
], trap=True)

_register("stress_trap_scope", "nl_stress", [
    ("sts1", "Filing the incident report and the injury claim in the same envelope is prohibited.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:file_incident_report", "action:file_injury_claim"]])], []),
    ("sts2", "Running the bleach cycle and the dye cycle together in one drum is forbidden.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:run_bleach_cycle", "action:run_dye_cycle"]])], []),
    ("sts3", "Publishing the trade figures and the supplier names in a single release is barred.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:publish_trade_figures", "action:publish_supplier_names"]])], []),
], trap=True)

_register("stress_trap_actor", "nl_stress", [
    ("sta1", "The duty groom may hand-feed the new mare.",
     [_structure("PERMISSION", "IF", [["action:hand_feed_new_mare"]], ["actor:duty_groom"])], ["actor:assistant"]),
    ("sta2", "Senior rangers may lead the night drive.",
     [_structure("PERMISSION", "IF", [["action:lead_night_drive"]], ["actor:senior_ranger"])], ["actor:assistant"]),
    ("sta3", "No one except the blast supervisor may arm the firing circuit.",
     [_structure("PERMISSION", "ONLY_IF", [["action:arm_firing_circuit"]], ["actor:blast_supervisor"])], ["actor:assistant"]),
    ("sta4", "The foaming line is off limits to everyone but the shift brewer.",
     [_structure("PERMISSION", "ONLY_IF", [["action:access_foaming_line"]], ["actor:shift_brewer"])], ["actor:assistant"]),
    ("sta5", "Only the lift supervisor may key the hoist override.",
     [_structure("PERMISSION", "ONLY_IF", [["action:key_hoist_override"]], ["actor:lift_supervisor"])], ["actor:assistant"]),
], trap=True)

_register("stress_multi_sentence_rule", "nl_stress", [
    ("smi1", "The archive lift has one rule. It does not run while the fire panel is isolated, and that stand-down holds until the panel is restored and the restoration is logged.",
     [_structure("PROHIBITION", "IF", [["action:run_archive_lift"]], ["state:fire_panel_isolated"], exceptions=["state:fire_panel_restored", "state:restoration_logged"], exception_mode="ALL")], []),
    ("smi2", "Grading follows a strict order here. The practical is marked only once the safety round is signed, and never before the written sheet is filed.",
     [_structure("PERMISSION", "ONLY_IF", [["action:mark_practical"]], ["state:safety_round_signed", "state:written_sheet_filed"], condition_mode="ALL")], []),
    ("smi3", "Two things gate the preview build: the encryption toggle is on and the privacy scan came back empty. Until both hold, the build stays internal.",
     [_structure("PERMISSION", "ONLY_IF", [["action:publish_preview_build"]], ["state:encryption_toggle_on", "state:privacy_scan_clean"], condition_mode="ALL")], []),
])

_register("stress_nested_clause", "nl_stress", [
    ("snc1", "Applications that involve a minor participant and that lack the guardian's countersignature must not be processed.",
     [_structure("PROHIBITION", "IF", [["action:process_application"]], ["state:minor_participant", "!state:guardian_countersignature"], condition_mode="ALL")], []),
    ("snc2", "Returns that were bought on the corporate card which the employer has since deactivated may not be refunded in cash.",
     [_structure("PROHIBITION", "IF", [["action:refund_in_cash"]], ["state:corporate_card_deactivated"])], []),
    ("snc3", "Technicians who skipped the annual recert and who are not on the supervisor's exception list may not touch the reactor bay tools.",
     [_structure("PROHIBITION", "IF", [["action:touch_reactor_bay_tools"]], ["!state:annual_recert_done", "!state:supervisor_exception_listed"], condition_mode="ALL")], []),
])

_register("stress_provenance", "nl_stress", [
    ("spr1", "Quote the dwell temperature exactly as the kiln controller displays it; handwritten notes are not a source for this figure.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:dwell_temperature"]], ["evidence:kiln_controller_display"], regulated_kind="INFORMATION", provenance="TOOL_RESULT")], []),
    ("spr2", "The visitor count is reported from the gate sensor stream alone — headcounts from memory are not acceptable.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:visitor_count"]], ["evidence:gate_sensor_stream"], regulated_kind="INFORMATION", provenance="TOOL_RESULT")], []),
])

_register("stress_cardinality_quantifier", "nl_stress", [
    ("scn1", "At most two escalations may be parked per queue, regardless of who parked them.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["state:escalations_parked_gt_2"]], quantification="AT_MOST_2", regulated_kind="STATE")], []),
    ("scn2", "Payment goes out by cheque or by bank transfer; splitting one invoice across both is not allowed.",
     [_structure("PROHIBITION", "AND_NOT_EACH", [["claim:cheque_paid", "claim:transfer_paid"]], quantification="NOT_BOTH")], []),
])

# ---------------------------------------------------------------------------
# Natural-language stress set, ambiguous (20): both readings carry textual
# support in natural prose.
# ---------------------------------------------------------------------------

_register("ambiguous_prose_if_onlyif", "nl_stress", [
    ("pam1", "Analysts who cleared the probity check are authorized to sign the exposure memo.",
     [_structure("PERMISSION", "IF", [["action:sign_exposure_memo"]], ["state:probity_check_cleared"]),
      _structure("PERMISSION", "ONLY_IF", [["action:sign_exposure_memo"]], ["state:probity_check_cleared"])], []),
    ("pam2", "Cafes with a current hygiene rating can display the inspection certificate.",
     [_structure("PERMISSION", "IF", [["action:display_inspection_certificate"]], ["state:hygiene_rating_current"]),
      _structure("PERMISSION", "ONLY_IF", [["action:display_inspection_certificate"]], ["state:hygiene_rating_current"])], []),
    ("pam3", "Guards holding a firearm endorsement are permitted to staff the armored gate.",
     [_structure("PERMISSION", "IF", [["action:staff_armored_gate"]], ["state:firearm_endorsement_held"]),
      _structure("PERMISSION", "ONLY_IF", [["action:staff_armored_gate"]], ["state:firearm_endorsement_held"])], []),
    ("pam4", "Vets enrolled in the recall program may order the trace serum.",
     [_structure("PERMISSION", "IF", [["action:order_trace_serum"]], ["state:recall_program_enrolled"]),
      _structure("PERMISSION", "ONLY_IF", [["action:order_trace_serum"]], ["state:recall_program_enrolled"])], []),
    ("pam5", "Members of the gliding club who completed the spin training can fly the single-seater.",
     [_structure("PERMISSION", "IF", [["action:fly_single_seater"]], ["state:spin_training_completed"]),
      _structure("PERMISSION", "ONLY_IF", [["action:fly_single_seater"]], ["state:spin_training_completed"])], []),
    ("pam6", "Subscribers whose payment cleared are entitled to unlock the premium tier.",
     [_structure("PERMISSION", "IF", [["action:unlock_premium_tier"]], ["state:payment_cleared"]),
      _structure("PERMISSION", "ONLY_IF", [["action:unlock_premium_tier"]], ["state:payment_cleared"])], []),
])

_register("ambiguous_prose_and_or", "nl_stress", [
    ("pao1", "The trade desk does not settle while the margin call is open or the clearinghouse flag is raised.",
     [_structure("PROHIBITION", "IF", [["action:settle_trade"]], ["state:margin_call_open", "state:clearinghouse_flag_raised"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:settle_trade"]], ["state:margin_call_open", "state:clearinghouse_flag_raised"], condition_mode="ALL")], []),
    ("pao2", "Sampling is off limits where the borehole is unsealed or the methane meter reads fault.",
     [_structure("PROHIBITION", "IF", [["action:sample_borehole"]], ["state:borehole_unsealed", "state:methane_meter_fault"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:sample_borehole"]], ["state:borehole_unsealed", "state:methane_meter_fault"], condition_mode="ALL")], []),
    ("pao3", "Do not assign the corner suite when the wedding block is active or the penthouse floor is in rotation.",
     [_structure("PROHIBITION", "IF", [["action:assign_corner_suite"]], ["state:wedding_block_active", "state:penthouse_in_rotation"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:assign_corner_suite"]], ["state:wedding_block_active", "state:penthouse_in_rotation"], condition_mode="ALL")], []),
    ("pao4", "The press desk stays dark until the embargo lifts or the wire feed confirms publication.",
     [_structure("PROHIBITION", "UNLESS", [["action:light_press_desk"]], exceptions=["state:embargo_lifted", "state:wire_feed_confirmed"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:light_press_desk"]], exceptions=["state:embargo_lifted", "state:wire_feed_confirmed"], exception_mode="ALL")], []),
])

_register("ambiguous_prose_exception", "nl_stress", [
    ("pax1", "The draft findings may not circulate beyond the team unless the lead reviewer or the ombudsman clears the wider sharing.",
     [_structure("PROHIBITION", "UNLESS", [["action:circulate_findings"]], exceptions=["state:lead_reviewer_clears", "state:ombudsman_clears"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:circulate_findings"]], exceptions=["state:lead_reviewer_clears", "state:ombudsman_clears"], exception_mode="ALL")], []),
    ("pax2", "Raw footage is not released unless the field producer or the compliance editor signs the release sheet.",
     [_structure("PROHIBITION", "UNLESS", [["action:release_raw_footage"]], exceptions=["state:field_producer_signed", "state:compliance_editor_signed"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:release_raw_footage"]], exceptions=["state:field_producer_signed", "state:compliance_editor_signed"], exception_mode="ALL")], []),
    ("pax3", "Do not book the long-haul slot unless the route is recertified or the ferry waiver is active.",
     [_structure("PROHIBITION", "UNLESS", [["action:book_longhaul_slot"]], exceptions=["state:route_recertified", "state:ferry_waiver_active"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:book_longhaul_slot"]], exceptions=["state:route_recertified", "state:ferry_waiver_active"], exception_mode="ALL")], []),
    ("pax4", "The cellar door stays shut unless the tasting host or the cellar hand is rostered on.",
     [_structure("PROHIBITION", "UNLESS", [["action:open_cellar_door"]], exceptions=["state:tasting_host_rostered", "state:cellar_hand_rostered"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:open_cellar_door"]], exceptions=["state:tasting_host_rostered", "state:cellar_hand_rostered"], exception_mode="ALL")], []),
])

_register("ambiguous_prose_temporal", "nl_stress", [
    ("pat1", "The crane pad may be released once the load test is signed off.",
     [_structure("PERMISSION", "IF", [["action:release_crane_pad"]], ["event:load_test_signed_off"], temporal="AFTER"),
      _structure("PERMISSION", "ONLY_IF", [["action:release_crane_pad"]], ["event:load_test_signed_off"], temporal="AFTER")], []),
    ("pat2", "You may open the trading floor once the regulator's letter arrives.",
     [_structure("PERMISSION", "IF", [["action:open_trading_floor"]], ["event:regulator_letter_arrived"], temporal="AFTER"),
      _structure("PERMISSION", "ONLY_IF", [["action:open_trading_floor"]], ["event:regulator_letter_arrived"], temporal="AFTER")], []),
])

_register("ambiguous_prose_scope_attachment", "nl_stress", [
    ("pas1", "Do not forward the contract and the exhibits.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:forward_contract", "action:forward_exhibits"]]),
      _structure("PROHIBITION", "UNCONDITIONAL", [["action:forward_contract"], ["action:forward_exhibits"]])], []),
    ("pas2", "Do not copy the master tape and the log sheet.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:copy_master_tape", "action:copy_log_sheet"]]),
      _structure("PROHIBITION", "UNCONDITIONAL", [["action:copy_master_tape"], ["action:copy_log_sheet"]])], []),
    ("pas3", "Do not archive the consent letter and the biopsy report at the end of the visit.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:archive_consent_letter", "action:archive_biopsy_report"]]),
      _structure("PROHIBITION", "UNCONDITIONAL", [["action:archive_consent_letter"], ["action:archive_biopsy_report"]])], []),
    ("pas4", "Do not shred the draft affidavit and the exhibit bundle during the case review.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:shred_draft_affidavit", "action:shred_exhibit_bundle"]]),
      _structure("PROHIBITION", "UNCONDITIONAL", [["action:shred_draft_affidavit"], ["action:shred_exhibit_bundle"]])], []),
])


def _positive_atoms(structure: dict) -> set:
    atoms = set()
    for clause in structure["target_clauses"]:
        for literal in clause:
            atoms.add(literal[1:] if literal.startswith("!") else literal)
    for name in ("condition_literals", "exception_literals"):
        for literal in structure[name]:
            atoms.add(literal[1:] if literal.startswith("!") else literal)
    return atoms


def build_v5_benchmark(seed: int = 260915) -> list[PolicyV5Case]:
    """Build the frozen v5 case set deterministically: 94 unambiguous, 48 ambiguous."""
    rng = random.Random(seed)
    cases: list[PolicyV5Case] = []
    for family, style, entries, trap in V5_TEMPLATES:
        for entry in entries:
            key, text, structures, extra_atoms = entry
            structures = [dict(structure) for structure in structures]
            atoms = set()
            for structure in structures:
                atoms.update(_positive_atoms(structure))
            atoms.update(extra_atoms)
            distractor = f"distractor:{family}_{key}"
            atom_catalog = tuple(sorted(atoms | {distractor}))
            programs = [compile_v3_structure(structure) for structure in structures]
            ambiguous = len(structures) > 1
            if trap and ambiguous:
                raise ValueError(f"trap families must be unambiguous: {family}::{key}")
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
            case = PolicyV5Case(
                case_id=f"{family}::{key}", family=family, style=style, policy=text,
                atom_catalog=atom_catalog, ambiguous=ambiguous, trap=trap,
                admissible_structures=tuple(structures),
                admissible_programs=tuple({json.dumps(p, sort_keys=True): p for p in programs}.values()),
                worlds=tuple(worlds))
            cases.append(case)
    rng.shuffle(cases)
    return sorted(cases, key=lambda case: case.case_id)


def benchmark_v5_document(cases: list[PolicyV5Case]) -> dict:
    rows = [case.as_dict() for case in cases]
    return {"schema_version": "guardian-vnext-policy-v5-benchmark-v1",
            "frozen_before_predictions": True,
            "annotation_basis": "CONSTRUCTION_FROM_TEMPLATES_NOT_MODEL_LABELS",
            "styles": ["controlled", "nl_stress"],
            "cases_sha256": digest(rows), "cases": rows}


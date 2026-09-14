"""Policy v4 controlled benchmark: 120 cases, gold by construction.

Two representation classes reduce slot-alignment risk: a controlled
replication set (semantics-first templates, fresh entities and phrasings) and
a natural-language stress set (long sentences, nested clauses, cross-sentence
references, indirect modality phrasings). 40 cases are genuinely ambiguous:
each carries two behaviorally distinct admissible readings, and 36 of the 40
are reachable from one reading to the other by exactly one catalog mutation
(relation flip, condition-mode flip, exception-mode flip, target-scope
merge/split); the four actor cases are restrictive-vs-descriptive readings
that the catalog deliberately cannot reach, as an honest ceiling probe.

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
class PolicyV4Case:
    case_id: str
    family: str
    style: str
    policy: str
    atom_catalog: tuple
    ambiguous: bool
    admissible_structures: tuple
    admissible_programs: tuple
    worlds: tuple

    def as_dict(self) -> dict:
        return {"case_id": self.case_id, "family": self.family, "style": self.style,
                "policy": self.policy, "atom_catalog": list(self.atom_catalog),
                "ambiguous": self.ambiguous,
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
V4_TEMPLATES: list[tuple] = []


def _register(family, style, cases):
    V4_TEMPLATES.append((family, style, cases))


# ---------------------------------------------------------------------------
# Controlled replication set (40 unambiguous).
# ---------------------------------------------------------------------------

_register("direction_if_onlyif_iff", "controlled", [
    ("iff", "The escalation may be marked resolved if and only if the root-cause note has been filed.",
     [_structure("PERMISSION", "IF_AND_ONLY_IF", [["action:mark_resolved"]], ["state:root_cause_note_filed"])], []),
    ("if", "If the claim adjuster has countersigned the estimate, you may schedule the inspection.",
     [_structure("PERMISSION", "IF", [["action:schedule_inspection"]], ["state:estimate_countersigned"])], []),
    ("onlyif", "You may schedule the inspection only if the claim adjuster has countersigned the estimate.",
     [_structure("PERMISSION", "ONLY_IF", [["action:schedule_inspection"]], ["state:estimate_countersigned"])], []),
])
_register("requirement_if", "controlled", [
    ("if1", "If the permit application mentions a variance, attach the zoning board letter.",
     [_structure("REQUIREMENT", "IF", [["state:zoning_letter_attached"]], ["state:variance_mentioned"])], []),
    ("if2", "Whenever the admitting form flags a penicillin allergy, the nurse must add the allergy band.",
     [_structure("REQUIREMENT", "IF", [["state:allergy_band_added"]], ["state:penicillin_allergy_flagged"])], []),
])
_register("unconditional_prohibition", "controlled", [
    ("u1", "Never quote the internal tariff sheet in a customer-facing reply.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:quote_internal_tariff"]])], []),
    ("u2", "Do not archive a permit file that is still under appeal.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:archive_appealed_permit"]])], []),
])
_register("unconditional_requirement", "controlled", [
    ("r1", "Always record the meter serial number when opening a service ticket.",
     [_structure("REQUIREMENT", "UNCONDITIONAL", [["state:meter_serial_recorded"]])], []),
    ("r2", "Every discharge summary must carry the attending physician's code.",
     [_structure("REQUIREMENT", "UNCONDITIONAL", [["state:physician_code_present"]])], []),
])
_register("unless_exception", "controlled", [
    ("u1", "Do not release the towing records unless the records custodian has approved the disclosure.",
     [_structure("PROHIBITION", "UNLESS", [["action:release_towing_records"]], exceptions=["state:custodian_approved"])], []),
    ("u2", "Never override the dosage alert unless the senior pharmacist documents the override reason.",
     [_structure("PROHIBITION", "UNLESS", [["action:override_dosage_alert"]], exceptions=["state:pharmacist_documented"])], []),
])
_register("exception_condition_stack", "controlled", [
    ("s1", "Do not authorize the site visit if the contractor's insurance has lapsed, unless the risk office has granted a waiver.",
     [_structure("PROHIBITION", "IF", [["action:authorize_site_visit"]], ["state:insurance_lapsed"],
                 exceptions=["state:risk_waiver_granted"])], []),
    ("s2", "If the lab sample is unlabeled, results must not be reported unless the collection log reconciles the sample.",
     [_structure("PROHIBITION", "IF", [["action:report_results"]], ["state:sample_unlabeled"],
                 exceptions=["state:log_reconciled"])], []),
])
_register("and_or_condition", "controlled", [
    ("any", "Do not clear the freight container if the manifest is unsigned or the seal number is unreadable.",
     [_structure("PROHIBITION", "IF", [["action:clear_container"]], ["state:manifest_unsigned", "state:seal_unreadable"], condition_mode="ANY")], []),
    ("all", "Do not clear the freight container if both the manifest is unsigned and the seal number is unreadable.",
     [_structure("PROHIBITION", "IF", [["action:clear_container"]], ["state:manifest_unsigned", "state:seal_unreadable"], condition_mode="ALL")], []),
    ("any2", "Refuse the move-in request when either the deposit is unverified or the lease is unsigned.",
     [_structure("PROHIBITION", "IF", [["action:approve_move_in"]], ["state:deposit_unverified", "state:lease_unsigned"], condition_mode="ANY")], []),
])
_register("nested_qualifier", "controlled", [
    ("n1", "A pending claim may be escalated by its owner only after the escalation form is attached.",
     [_structure("PERMISSION", "ONLY_IF", [["action:escalate_claim"]], ["state:claim_pending", "identity:owner_of_claim", "state:escalation_form_attached"])], []),
    ("n2", "For a pending loan, disbursement is permitted only when the borrower has signed the disclosure and the file holds a credit approval.",
     [_structure("PERMISSION", "ONLY_IF", [["action:disburse_loan"]], ["state:loan_pending", "identity:requester_is_borrower", "state:disclosure_signed", "state:credit_approval_present"])], []),
    ("n3", "A pending badge may be issued to its requester only once the escort is assigned.",
     [_structure("PERMISSION", "ONLY_IF", [["action:issue_badge"]], ["state:badge_request_pending", "identity:requester_listed", "state:escort_assigned"])], []),
    ("n4", "Pending purchase orders can be amended by the raising department only after the change notice is filed.",
     [_structure("PERMISSION", "ONLY_IF", [["action:amend_purchase_order"]], ["state:po_pending", "identity:raising_department_requester", "state:change_notice_filed"])], []),
])
_register("actor_role", "controlled", [
    ("a1", "Only the custody officer may seal an evidence bag.",
     [_structure("PERMISSION", "ONLY_IF", [["action:seal_evidence_bag"]], ["actor:custody_officer"])],
     ["actor:assistant"]),
    ("a2", "Restocking the controlled cabinet is reserved to the pharmacy technician alone.",
     [_structure("PERMISSION", "ONLY_IF", [["action:restock_controlled_cabinet"]], ["actor:pharmacy_technician"])],
     ["actor:assistant"]),
    ("a3", "Only a sworn translator may certify the translated consent form.",
     [_structure("PERMISSION", "ONLY_IF", [["action:certify_translated_consent"]], ["actor:sworn_translator"])],
     ["actor:assistant"]),
])
_register("identity_same_entity", "controlled", [
    ("i1", "You may apply the voucher only to the reservation it was originally issued with.",
     [_structure("PERMISSION", "ONLY_IF", [["action:apply_voucher"]], ["identity:same_reservation"], identity="SAME_RESERVATION")], []),
    ("i2", "Do not transfer the license to an account other than the one that purchased it.",
     [_structure("PROHIBITION", "UNLESS", [["action:transfer_license"]], exceptions=["identity:same_purchasing_account"], identity="SAME_USER")], []),
])
_register("temporal_after_before", "controlled", [
    ("t1", "The auction lot may be released only after the payment has cleared.",
     [_structure("PERMISSION", "ONLY_IF", [["action:release_lot"]], ["event:payment_cleared"], temporal="AFTER")], []),
    ("t2", "You may revise the exhibit list only before the hearing convenes.",
     [_structure("PERMISSION", "ONLY_IF", [["action:revise_exhibit_list"]], ["!event:hearing_convened"], temporal="BEFORE")], []),
])
_register("provenance_source", "controlled", [
    ("p1", "State the meter reading only as it appears in the reading returned by the meter tool.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:meter_reading"]], ["evidence:meter_tool_reading"], regulated_kind="INFORMATION", provenance="TOOL_RESULT")], []),
    ("p2", "Support any damage estimate with the estimator's written figure.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:damage_estimate"]], ["evidence:estimator_written_figure"], regulated_kind="INFORMATION")], []),
])
_register("state_vs_action", "controlled", [
    ("s1", "Rebooking is permitted while the flight remains in same-day status.",
     [_structure("PERMISSION", "ONLY_IF", [["action:rebook_passenger"]], ["state:flight_same_day"])], []),
    ("s2", "Do not treat a submitted application as evidence that the fee was paid.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:fee_paid"]], ["evidence:payment_confirmation_observed"], regulated_kind="INFORMATION")], []),
])
_register("distractor_permission_language", "controlled", [
    ("x1", "Ticket prices may fluctuate until the fare window closes. Quote the fare only from the current fare table.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:fare_quote"]], ["evidence:current_fare_table"], regulated_kind="INFORMATION")], []),
    ("x2", "Port assignments can change between maintenance windows. Confirm the port against the running config before rerouting traffic.",
     [_structure("REQUIREMENT", "UNCONDITIONAL", [["state:port_confirmed_against_config"]])], []),
])
_register("genuine_permission_if", "controlled", [
    ("g1", "You are allowed to waive the restocking fee once the return is within the grace window.",
     [_structure("PERMISSION", "IF", [["action:waive_restocking_fee"]], ["state:return_within_grace"])], []),
    ("g2", "If the clinic has closed the episode, the agent may schedule the follow-up call.",
     [_structure("PERMISSION", "IF", [["action:schedule_follow_up"]], ["state:episode_closed"])], []),
])
_register("not_both_channels", "controlled", [
    ("c1", "For a single alert, send the page or the email, but never both in one notification round.",
     [_structure("PROHIBITION", "AND_NOT_EACH", [["turn:page_sent", "turn:email_sent"]], quantification="NOT_BOTH")], []),
    ("c2", "Do not bill the card and debit the wallet for the same installment.",
     [_structure("PROHIBITION", "AND_NOT_EACH", [["claim:card_billed", "claim:wallet_debited"]], quantification="NOT_BOTH")], []),
])
_register("cardinality_atmost", "controlled", [
    ("m1", "Each filing may carry at most two amended schedules.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["state:amended_schedules_gt_2"]], quantification="AT_MOST_2", regulated_kind="STATE")], []),
    ("m2", "No more than one courtesy credit is permitted per account per quarter.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["state:courtesy_credits_gt_1"]], quantification="AT_MOST_1_PER_TURN", regulated_kind="STATE")], []),
])
_register("turn_call_cardinality", "controlled", [
    ("k1", "A single assistant turn may pose at most one clarifying question.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["turn:clarifying_questions_gt_1"]], quantification="AT_MOST_1_PER_TURN")], []),
])

# ---------------------------------------------------------------------------
# Natural-language stress set (40 unambiguous).
# ---------------------------------------------------------------------------

_register("stress_multi_sentence_rule", "nl_stress", [
    ("m1", "Permit revocations follow a fixed procedure. The revocation letter goes out only after the appeals window closes with no challenge filed. Anything short of that remains blocked.",
     [_structure("PERMISSION", "ONLY_IF", [["action:send_revocation_letter"]], ["state:appeals_window_closed", "state:no_challenge_filed"], condition_mode="ALL")], []),
    ("m2", "The archive lock is not optional. Do not remove it while litigation is pending, and this restriction stays in force until counsel files the formal release.",
     [_structure("PROHIBITION", "IF", [["action:remove_archive_lock"]], ["state:litigation_pending"], exceptions=["state:counsel_release_filed"])], []),
    ("m3", "Equipment loans to visiting researchers need two signatures. Until both the lab manager and the safety officer have signed, the item may not leave storage.",
     [_structure("PERMISSION", "ONLY_IF", [["action:release_equipment"]], ["state:lab_manager_signed", "state:safety_officer_signed"], condition_mode="ALL")], []),
    ("m4", "Overdraft forgiveness applies narrowly. A fee may be reversed only when the account holder enrolled in balance alerts beforehand.",
     [_structure("PERMISSION", "ONLY_IF", [["action:reverse_overdraft_fee"]], ["state:balance_alerts_enrolled"])], []),
    ("m5", "Doors stay badge-only during the audit. Guests may not enter while the audit notice is posted, except when the lead auditor escorts them personally.",
     [_structure("PROHIBITION", "IF", [["action:guest_entry"]], ["state:audit_notice_posted"], exceptions=["state:lead_auditor_escorting"])], []),
])
_register("stress_nested_clause", "nl_stress", [
    ("n1", "Refunds that were issued to a card which the issuer has since retired must not be reprocessed through the original rail.",
     [_structure("PROHIBITION", "IF", [["action:reprocess_refund_original_rail"]], ["state:origin_card_retired"])], []),
    ("n2", "The clerk who accepts a filing that lacks the notarized cover sheet must record the deficiency in the intake log before docketing anything.",
     [_structure("REQUIREMENT", "IF", [["state:deficiency_recorded"]], ["state:filing_lacks_cover_sheet"])], []),
    ("n3", "Claims that involve a minor beneficiary and that have not been reviewed by the guardian liaison may not be settled out of turn.",
     [_structure("PROHIBITION", "IF", [["action:settle_claim"]], ["state:minor_beneficiary", "state:guardian_review_missing"], condition_mode="ALL")], []),
    ("n4", "Adjustments posted to an account that was frozen during the fraud sweep may be kept only with the fraud desk's written concurrence.",
     [_structure("PERMISSION", "ONLY_IF", [["action:keep_adjustment"]], ["state:account_frozen", "state:written_concurrence"], condition_mode="ALL")], []),
    ("n5", "Candidates who arrive after the testing center has closed its doors are not to be seated, even if their confirmation email shows an earlier slot.",
     [_structure("PROHIBITION", "IF", [["action:seat_candidate"]], ["state:doors_closed"])], []),
])
_register("stress_lexical_indirect", "nl_stress", [
    ("l1", "Under no circumstances is the settlement figure to be disclosed to anyone outside the claims department.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:disclose_settlement_figure"]])], []),
    ("l2", "Approval of the change request is conditioned solely on the release manager's sign-off.",
     [_structure("PERMISSION", "ONLY_IF", [["action:approve_change_request"]], ["state:release_manager_signed"])], []),
    ("l3", "The warehouse inventory figure is to be stated only from the cycle-count sheet that the inventory tool most recently produced.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:inventory_figure"]], ["evidence:latest_cycle_count_sheet"], regulated_kind="INFORMATION", provenance="FRESH_TOOL_READ")], []),
    ("l4", "No islanding command may go out before the duty engineer has confirmed grid frequency.",
     [_structure("PERMISSION", "ONLY_IF", [["action:send_islanding_command"]], ["event:frequency_confirmed"], temporal="AFTER")], []),
    ("l5", "A gate change announcement is not to be made unless the boarding system has accepted the new gate.",
     [_structure("PROHIBITION", "UNLESS", [["action:announce_gate_change"]], exceptions=["state:system_accepted_new_gate"])], []),
])
_register("stress_direction", "nl_stress", [
    ("d1", "The sole circumstance in which overtime may be pre-approved is a posted severity-one incident.",
     [_structure("PERMISSION", "ONLY_IF", [["action:preapprove_overtime"]], ["state:severity_one_incident"])], []),
    ("d2", "A shipment is eligible for the priority lane whenever it carries a certified cold-chain seal.",
     [_structure("PERMISSION", "IF", [["action:use_priority_lane"]], ["state:cold_chain_seal_certified"])], []),
    ("d3", "Reactivation of the suspended license is possible only where the reinstatement fee shows as cleared in the ledger.",
     [_structure("PERMISSION", "ONLY_IF", [["action:reactivate_license"]], ["state:reinstatement_fee_cleared"])], []),
    ("d4", "Wherever a tariff exception applies, the agent may reprice the line item at the exception rate.",
     [_structure("PERMISSION", "IF", [["action:reprice_at_exception_rate"]], ["state:tariff_exception_applies"])], []),
])
_register("stress_exception_temporal", "nl_stress", [
    ("e1", "The clinical note stays sealed until the review board lifts the seal.",
     [_structure("PROHIBITION", "UNLESS", [["action:unseal_clinical_note"]], exceptions=["state:board_lifted_seal"])], []),
    ("e2", "Late filings are rejected outright, except when the registry's own outage notice covers the missed window.",
     [_structure("PROHIBITION", "IF", [["action:accept_late_filing"]], ["state:filing_late"], exceptions=["state:outage_notice_covers"])], []),
    ("e3", "Retaking the placement exam is barred until the coaching module has been completed, unless the advisor grants an early attempt.",
     [_structure("PROHIBITION", "IF", [["action:retake_exam"]], ["!state:coaching_module_completed"], exceptions=["state:advisor_early_attempt_granted"])], []),
    ("e4", "During the embargo, media inquiries may be answered only from the prepared statement, unless counsel approves an exception.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:media_answer"]], ["evidence:prepared_statement"], regulated_kind="INFORMATION", exceptions=["state:counsel_exception_approved"])], []),
])
_register("stress_actor_condition", "nl_stress", [
    ("a1", "No one other than the charge nurse may adjust the infusion rate on a running drip.",
     [_structure("PERMISSION", "ONLY_IF", [["action:adjust_infusion_rate"]], ["actor:charge_nurse"])], ["actor:assistant"]),
    ("a2", "The duty pilot is the only person permitted to sign the fuel release, and only when the fueler's ticket matches the aircraft.",
     [_structure("PERMISSION", "ONLY_IF", [["action:sign_fuel_release"]], ["actor:duty_pilot", "state:ticket_matches_aircraft"], condition_mode="ALL")], ["actor:assistant"]),
    ("a3", "Escalation to tier three is reserved to the incident commander while the bridge call is active.",
     [_structure("PERMISSION", "ONLY_IF", [["action:escalate_tier_three"]], ["actor:incident_commander", "state:bridge_call_active"], condition_mode="ALL")], ["actor:assistant"]),
    ("a4", "Only the archivist, and only after the retention clock has run out, may shred the case file.",
     [_structure("PERMISSION", "ONLY_IF", [["action:shred_case_file"]], ["actor:archivist", "event:retention_clock_expired"], condition_mode="ALL")], ["actor:assistant"]),
])
_register("stress_provenance_exception", "nl_stress", [
    ("p1", "The damage figure may be quoted only as written in the adjuster's report, except when the reinspection memo supersedes it.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:damage_figure"]], ["evidence:adjuster_report_text"], regulated_kind="INFORMATION", exceptions=["state:reinspection_memo_supersedes"])], []),
    ("p2", "Present the outstanding balance exactly as the billing tool states it; the only exception is a supervisor-documented reconciliation.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:outstanding_balance"]], ["evidence:billing_tool_state"], regulated_kind="INFORMATION", exceptions=["state:supervisor_reconciliation_documented"])], []),
    ("p3", "Flight status must be reported from the operations feed alone, except where the airport's own delay bulletin is more recent.",
     [_structure("REQUIREMENT", "ONLY_IF", [["claim:flight_status"]], ["evidence:operations_feed"], regulated_kind="INFORMATION", exceptions=["state:delay_bulletin_more_recent"])], []),
])
_register("stress_nested_qualifier_prose", "nl_stress", [
    ("q1", "A pending enrolment may be withdrawn by the student who placed it, provided the withdrawal form has been countersigned by the registrar.",
     [_structure("PERMISSION", "ONLY_IF", [["action:withdraw_enrolment"]], ["state:enrolment_pending", "identity:placing_student_requester", "state:withdrawal_form_countersigned"])], []),
    ("q2", "If the grant file is in review, the disbursement can be released only to the principal investigator whose name is on the award letter, and only once the finance office countersigns.",
     [_structure("PERMISSION", "ONLY_IF", [["action:release_disbursement"]], ["state:grant_file_in_review", "identity:pi_on_award_letter", "state:finance_countersigned"])], []),
    ("q3", "Documents still under review may be checked out by their assigned examiner only, and only while the checkout window is open.",
     [_structure("PERMISSION", "ONLY_IF", [["action:checkout_document"]], ["state:document_under_review", "identity:assigned_examiner", "state:checkout_window_open"])], []),
    ("q4", "A pending transfer may be cancelled by the originating officer alone, and only after both the sending and receiving branches have acknowledged it.",
     [_structure("PERMISSION", "ONLY_IF", [["action:cancel_transfer"]], ["state:transfer_pending", "identity:originating_officer", "state:branches_acknowledged"])], []),
])
_register("stress_cardinality_quantifier", "nl_stress", [
    ("c1", "At most two price overrides are honored per cart, no matter who requests them.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["state:price_overrides_gt_2"]], quantification="AT_MOST_2", regulated_kind="STATE")], []),
    ("c2", "The declaration is valid with exactly one witness signature; any other count invalidates it.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["state:witness_count_not_one"]], quantification="ALL", regulated_kind="STATE")], []),
    ("c3", "At most one courtesy vaccination is offered per visit.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["state:courtesy_vaccinations_gt_1"]], quantification="AT_MOST_1_PER_TURN", regulated_kind="STATE")], []),
])
_register("stress_not_both", "nl_stress", [
    ("b1", "Route the alert either through the pager tree or through the ops channel — under no circumstances both for the same alert.",
     [_structure("PROHIBITION", "AND_NOT_EACH", [["turn:pager_tree_used", "turn:ops_channel_used"]], quantification="NOT_BOTH")], []),
    ("b2", "The refund goes to the original payment method or to store credit, never to both for one return.",
     [_structure("PROHIBITION", "AND_NOT_EACH", [["claim:original_method_refunded", "claim:store_credit_issued"]], quantification="NOT_BOTH")], []),
    ("b3", "Either the notary or the witnessing attorney signs the affidavit; having both sign renders it irregular.",
     [_structure("PROHIBITION", "AND_NOT_EACH", [["claim:notary_signed", "claim:attorney_signed"]], quantification="NOT_BOTH")], []),
])

# ---------------------------------------------------------------------------
# Ambiguous set (40 cases, two admissible readings each).
# ---------------------------------------------------------------------------

_register("ambiguous_if_onlyif", "controlled", [
    ("am1", "Customers with a paid deposit may select a cabin.",
     [_structure("PERMISSION", "IF", [["action:select_cabin"]], ["state:deposit_paid"]),
      _structure("PERMISSION", "ONLY_IF", [["action:select_cabin"]], ["state:deposit_paid"])], []),
    ("am2", "Agents holding the tier-two certificate can approve the return.",
     [_structure("PERMISSION", "IF", [["action:approve_return"]], ["state:tier_two_certificate_held"]),
      _structure("PERMISSION", "ONLY_IF", [["action:approve_return"]], ["state:tier_two_certificate_held"])], []),
    ("am3", "Vessels carrying hazardous cargo are allowed to use the outer berth.",
     [_structure("PERMISSION", "IF", [["action:use_outer_berth"]], ["state:hazardous_cargo"]),
      _structure("PERMISSION", "ONLY_IF", [["action:use_outer_berth"]], ["state:hazardous_cargo"])], []),
    ("am4", "Librarians with archive clearance may retrieve the rare folio.",
     [_structure("PERMISSION", "IF", [["action:retrieve_rare_folio"]], ["state:archive_clearance_held"]),
      _structure("PERMISSION", "ONLY_IF", [["action:retrieve_rare_folio"]], ["state:archive_clearance_held"])], []),
    ("am5", "Sponsors whose fee has cleared may collect the booth kit.",
     [_structure("PERMISSION", "IF", [["action:collect_booth_kit"]], ["state:sponsor_fee_cleared"]),
      _structure("PERMISSION", "ONLY_IF", [["action:collect_booth_kit"]], ["state:sponsor_fee_cleared"])], []),
    ("am6", "Tenants with a registered key fob can book the rooftop terrace.",
     [_structure("PERMISSION", "IF", [["action:book_rooftop_terrace"]], ["state:key_fob_registered"]),
      _structure("PERMISSION", "ONLY_IF", [["action:book_rooftop_terrace"]], ["state:key_fob_registered"])], []),
])
_register("ambiguous_if_onlyif", "nl_stress", [
    ("sm1", "Analysts who completed the bias workshop are authorized to close the review.",
     [_structure("PERMISSION", "IF", [["action:close_review"]], ["state:bias_workshop_completed"]),
      _structure("PERMISSION", "ONLY_IF", [["action:close_review"]], ["state:bias_workshop_completed"])], []),
    ("sm2", "Restaurants with a current grade card may post the certificate in the window.",
     [_structure("PERMISSION", "IF", [["action:post_certificate"]], ["state:current_grade_card"]),
      _structure("PERMISSION", "ONLY_IF", [["action:post_certificate"]], ["state:current_grade_card"])], []),
    ("sm3", "Employees enrolled in the shuttle program can reserve a parking spot.",
     [_structure("PERMISSION", "IF", [["action:reserve_parking_spot"]], ["state:shuttle_program_enrolled"]),
      _structure("PERMISSION", "ONLY_IF", [["action:reserve_parking_spot"]], ["state:shuttle_program_enrolled"])], []),
    ("sm4", "Delegates whose credentials have been verified are entitled to vote on the motion.",
     [_structure("PERMISSION", "IF", [["action:vote_on_motion"]], ["state:credentials_verified"]),
      _structure("PERMISSION", "ONLY_IF", [["action:vote_on_motion"]], ["state:credentials_verified"])], []),
    ("sm5", "Instructors holding a current aerobatic endorsement may fly the advanced routine.",
     [_structure("PERMISSION", "IF", [["action:fly_advanced_routine"]], ["state:aerobatic_endorsement_current"]),
      _structure("PERMISSION", "ONLY_IF", [["action:fly_advanced_routine"]], ["state:aerobatic_endorsement_current"])], []),
    ("sm6", "Contractors whose bonding certificate is on file are permitted to submit sealed bids.",
     [_structure("PERMISSION", "IF", [["action:submit_sealed_bid"]], ["state:bonding_certificate_on_file"]),
      _structure("PERMISSION", "ONLY_IF", [["action:submit_sealed_bid"]], ["state:bonding_certificate_on_file"])], []),
])
_register("ambiguous_and_or", "controlled", [
    ("ao1", "Do not release the transcript if the hold is active or the balance is unpaid.",
     [_structure("PROHIBITION", "IF", [["action:release_transcript"]], ["state:hold_active", "state:balance_unpaid"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:release_transcript"]], ["state:hold_active", "state:balance_unpaid"], condition_mode="ALL")], []),
    ("ao2", "Do not unlock the lab if the calibration is overdue or the safety inspection has lapsed.",
     [_structure("PROHIBITION", "IF", [["action:unlock_lab"]], ["state:calibration_overdue", "state:safety_inspection_lapsed"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:unlock_lab"]], ["state:calibration_overdue", "state:safety_inspection_lapsed"], condition_mode="ALL")], []),
    ("ao3", "Refuse the copy request if the requester's ID is expired or the consent form is unsigned.",
     [_structure("PROHIBITION", "IF", [["action:fulfill_copy_request"]], ["state:requester_id_expired", "state:consent_form_unsigned"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:fulfill_copy_request"]], ["state:requester_id_expired", "state:consent_form_unsigned"], condition_mode="ALL")], []),
    ("ao4", "Do not dispatch the crew if the roster is incomplete or the medical clearance is missing.",
     [_structure("PROHIBITION", "IF", [["action:dispatch_crew"]], ["state:roster_incomplete", "state:medical_clearance_missing"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:dispatch_crew"]], ["state:roster_incomplete", "state:medical_clearance_missing"], condition_mode="ALL")], []),
])
_register("ambiguous_and_or", "nl_stress", [
    ("so1", "The keys stay with the front desk while the deposit is unreturned or the inspection is unsigned.",
     [_structure("PROHIBITION", "IF", [["action:hand_out_keys"]], ["state:deposit_unreturned", "state:inspection_unsigned"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:hand_out_keys"]], ["state:deposit_unreturned", "state:inspection_unsigned"], condition_mode="ALL")], []),
    ("so2", "Escalations must not be closed while the root cause is undetermined or the patch is unverified.",
     [_structure("PROHIBITION", "IF", [["action:close_escalation"]], ["state:root_cause_undetermined", "state:patch_unverified"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:close_escalation"]], ["state:root_cause_undetermined", "state:patch_unverified"], condition_mode="ALL")], []),
    ("so3", "Sampling is not permitted where the batch is quarantined or the COA is absent.",
     [_structure("PROHIBITION", "IF", [["action:sample_batch"]], ["state:batch_quarantined", "state:coa_absent"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:sample_batch"]], ["state:batch_quarantined", "state:coa_absent"], condition_mode="ALL")], []),
    ("so4", "Do not book the audition slot when the accompanist fee is unpaid or the sheet music is on hold.",
     [_structure("PROHIBITION", "IF", [["action:book_audition_slot"]], ["state:accompanist_fee_unpaid", "state:sheet_music_on_hold"], condition_mode="ANY"),
      _structure("PROHIBITION", "IF", [["action:book_audition_slot"]], ["state:accompanist_fee_unpaid", "state:sheet_music_on_hold"], condition_mode="ALL")], []),
])
_register("ambiguous_exception_mode", "controlled", [
    ("ax1", "Do not reopen the excavation unless the site inspector or the project engineer has signed off.",
     [_structure("PROHIBITION", "UNLESS", [["action:reopen_excavation"]], exceptions=["state:inspector_signed", "state:engineer_signed"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:reopen_excavation"]], exceptions=["state:inspector_signed", "state:engineer_signed"], exception_mode="ALL")], []),
    ("ax2", "Do not merge the records unless the registrar or the deputy registrar approves.",
     [_structure("PROHIBITION", "UNLESS", [["action:merge_records"]], exceptions=["state:registrar_approved", "state:deputy_approved"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:merge_records"]], exceptions=["state:registrar_approved", "state:deputy_approved"], exception_mode="ALL")], []),
    ("ax3", "Never skip the disinfection step unless the sterilization log or the duty log documents the exception.",
     [_structure("PROHIBITION", "UNLESS", [["action:skip_disinfection"]], exceptions=["state:sterilization_log_documented", "state:duty_log_documented"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:skip_disinfection"]], exceptions=["state:sterilization_log_documented", "state:duty_log_documented"], exception_mode="ALL")], []),
])
_register("ambiguous_exception_mode", "nl_stress", [
    ("sx1", "The draft may not leave the working group unless the chair or the methodologist approves the wider release.",
     [_structure("PROHIBITION", "UNLESS", [["action:circulate_draft"]], exceptions=["state:chair_approves", "state:methodologist_approves"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:circulate_draft"]], exceptions=["state:chair_approves", "state:methodologist_approves"], exception_mode="ALL")], []),
    ("sx2", "Backups are not to be purged unless the retention officer or the privacy officer signs the purge order.",
     [_structure("PROHIBITION", "UNLESS", [["action:purge_backup"]], exceptions=["state:retention_officer_signed", "state:privacy_officer_signed"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:purge_backup"]], exceptions=["state:retention_officer_signed", "state:privacy_officer_signed"], exception_mode="ALL")], []),
    ("sx3", "Do not substitute the generic reagent unless the lab supervisor or the pharmacy lead authorizes it in writing.",
     [_structure("PROHIBITION", "UNLESS", [["action:substitute_generic_reagent"]], exceptions=["state:supervisor_authorized", "state:pharmacy_lead_authorized"], exception_mode="ANY"),
      _structure("PROHIBITION", "UNLESS", [["action:substitute_generic_reagent"]], exceptions=["state:supervisor_authorized", "state:pharmacy_lead_authorized"], exception_mode="ALL")], []),
])
_register("ambiguous_temporal", "controlled", [
    ("at1", "You may amend the flight plan before the final boarding call.",
     [_structure("PERMISSION", "IF", [["action:amend_flight_plan"]], ["!event:final_call_made"], temporal="BEFORE"),
      _structure("PERMISSION", "ONLY_IF", [["action:amend_flight_plan"]], ["!event:final_call_made"], temporal="BEFORE")], []),
    ("at2", "The gate may be reassigned once the delay code is posted.",
     [_structure("PERMISSION", "IF", [["action:reassign_gate"]], ["event:delay_code_posted"], temporal="AFTER"),
      _structure("PERMISSION", "ONLY_IF", [["action:reassign_gate"]], ["event:delay_code_posted"], temporal="AFTER")], []),
])
_register("ambiguous_temporal", "nl_stress", [
    ("st1", "The hold may be lifted after the compliance review concludes.",
     [_structure("PERMISSION", "IF", [["action:lift_hold"]], ["event:compliance_review_concluded"], temporal="AFTER"),
      _structure("PERMISSION", "ONLY_IF", [["action:lift_hold"]], ["event:compliance_review_concluded"], temporal="AFTER")], []),
    ("st2", "Field measurements may be logged while the survey is in progress.",
     [_structure("PERMISSION", "IF", [["action:log_measurement"]], ["state:survey_in_progress"]),
      _structure("PERMISSION", "ONLY_IF", [["action:log_measurement"]], ["state:survey_in_progress"])], []),
    ("st3", "The agent may reissue the boarding pass once the standby list clears.",
     [_structure("PERMISSION", "IF", [["action:reissue_boarding_pass"]], ["event:standby_list_cleared"], temporal="AFTER"),
      _structure("PERMISSION", "ONLY_IF", [["action:reissue_boarding_pass"]], ["event:standby_list_cleared"], temporal="AFTER")], []),
])
_register("ambiguous_scope", "controlled", [
    ("sc1", "Do not cancel the room reservation and the car reservation.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:cancel_room", "action:cancel_car"]]),
      _structure("PROHIBITION", "UNCONDITIONAL", [["action:cancel_room"], ["action:cancel_car"]])], []),
    ("sc2", "Do not close the order and the claim simultaneously.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:close_order", "action:close_claim"]]),
      _structure("PROHIBITION", "UNCONDITIONAL", [["action:close_order"], ["action:close_claim"]])], []),
])
_register("ambiguous_scope", "nl_stress", [
    ("ss1", "Do not approve the loan and the grant request.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:approve_loan", "action:approve_grant"]]),
      _structure("PROHIBITION", "UNCONDITIONAL", [["action:approve_loan"], ["action:approve_grant"]])], []),
    ("ss2", "Do not archive the transcript and the exam file.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:archive_transcript", "action:archive_exam_file"]]),
      _structure("PROHIBITION", "UNCONDITIONAL", [["action:archive_transcript"], ["action:archive_exam_file"]])], []),
    ("ss3", "Do not disclose the audit summary and the personnel file.",
     [_structure("PROHIBITION", "UNCONDITIONAL", [["action:disclose_audit_summary", "action:disclose_personnel_file"]]),
      _structure("PROHIBITION", "UNCONDITIONAL", [["action:disclose_audit_summary"], ["action:disclose_personnel_file"]])], []),
])
_register("ambiguous_actor", "controlled", [
    ("aa1", "The registrar may amend the student record.",
     [_structure("PERMISSION", "ONLY_IF", [["action:amend_student_record"]], ["actor:registrar"]),
      _structure("PERMISSION", "UNCONDITIONAL", [["action:amend_student_record"]])], ["actor:assistant"]),
    ("aa2", "The duty pharmacist may dispense the controlled sample.",
     [_structure("PERMISSION", "ONLY_IF", [["action:dispense_controlled_sample"]], ["actor:duty_pharmacist"]),
      _structure("PERMISSION", "UNCONDITIONAL", [["action:dispense_controlled_sample"]])], ["actor:assistant"]),
])
_register("ambiguous_actor", "nl_stress", [
    ("sa1", "The site foreman may authorize the concrete pour.",
     [_structure("PERMISSION", "ONLY_IF", [["action:authorize_concrete_pour"]], ["actor:site_foreman"]),
      _structure("PERMISSION", "UNCONDITIONAL", [["action:authorize_concrete_pour"]])], ["actor:assistant"]),
    ("sa2", "The vault teller may release the sealed deposit.",
     [_structure("PERMISSION", "ONLY_IF", [["action:release_sealed_deposit"]], ["actor:vault_teller"]),
      _structure("PERMISSION", "UNCONDITIONAL", [["action:release_sealed_deposit"]])], ["actor:assistant"]),
])


def _positive_atoms(structure: dict) -> set:
    atoms = set()
    for clause in structure["target_clauses"]:
        for literal in clause:
            if not literal.startswith("!"):
                atoms.add(literal)
            else:
                atoms.add(literal[1:])
    for name in ("condition_literals", "exception_literals"):
        for literal in structure[name]:
            if literal.startswith("!"):
                atoms.add(literal[1:])
            else:
                atoms.add(literal)
    return atoms


def build_v4_benchmark(seed: int = 260914) -> list[PolicyV4Case]:
    """Build the frozen v4 case set deterministically: 40+40 unambiguous, 40 ambiguous."""
    rng = random.Random(seed)
    cases: list[PolicyV4Case] = []
    for family, style, entries in V4_TEMPLATES:
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
            case = PolicyV4Case(
                case_id=f"{family}::{key}", family=family, style=style, policy=text,
                atom_catalog=atom_catalog, ambiguous=ambiguous,
                admissible_structures=tuple(structures),
                admissible_programs=tuple({json.dumps(p, sort_keys=True): p for p in programs}.values()),
                worlds=tuple(worlds))
            cases.append(case)
    rng.shuffle(cases)
    return sorted(cases, key=lambda case: case.case_id)


def benchmark_v4_document(cases: list[PolicyV4Case]) -> dict:
    rows = [case.as_dict() for case in cases]
    return {"schema_version": "guardian-vnext-policy-v4-benchmark-v1",
            "frozen_before_predictions": True,
            "annotation_basis": "CONSTRUCTION_FROM_TEMPLATES_NOT_MODEL_LABELS",
            "styles": ["controlled", "nl_stress"],
            "cases_sha256": digest(rows), "cases": rows}


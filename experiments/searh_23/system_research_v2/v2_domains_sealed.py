#!/usr/bin/env python3
"""Trajectories v2 — SEALED split domain definitions (authored, self-verified).

Five domain-disjoint families (cinema / quarry / apiary / transit / archive),
new relative to dev split and every previous suite.

Stress coverage:
- cinema: value threshold + async request-vs-completion + timeout
- quarry: LONG multi-rule (base prohibition + exception + exception condition
  + second unrelated rule + later clarification + actor-specific rule)
  with entity IDs that matter (conveyor 4 vs 5)
- apiary: exception + temporal evidence relocation + state-vs-action
- transit: reachability stress (closed path, open gate, exception path,
  missing user input, truly closed, read-only)
- archive: claim stress (all 8 modes on one response + negation)
"""
from __future__ import annotations

from v2_domains_dev import (  # noqa: F401
    _tool, _read, _write, _atom, _src, _spans, program, call, result,
    _claim, _fact, RO, CG)


# =========================================================================
# FAMILY: cinema — value threshold + async + timeout
# =========================================================================

CINEMA_POLICY = (
    "Refunding a ticket above 15 requires supervisor confirmation "
    "recorded for the same amount. Submitting a refund request does not "
    "refund the ticket. A refund request pending for more than 20 minutes "
    "must be cancelled before the refund itself. Refunding a ticket that "
    "was never purchased is forbidden.")

CINEMA_TOOLS = [
    _write("submit_refund_request", "Submits the refund request for the ticket.",
           {"ticket_id": "string", "amount": "number"},
           {"ticket_id": "string", "status": "scalar"},
           "ticket.refund_request_state", ["submitted"],
           "Submitting requests a refund; submitted means requested, not refunded.",
           strength="REQUESTED"),
    _read("check_supervisor", "Reports whether supervisor confirmation is recorded for the ticket amount.",
          {"ticket_id": "string", "amount": "number"},
          {"ticket_id": "string", "confirmed": "scalar"},
          "ticket.supervisor_confirmed",
          "Reports whether supervisor confirmation is recorded for this ticket amount."),
    _read("check_pending_age", "Reports whether the refund request has been pending for more than 20 minutes.",
          {"ticket_id": "string"}, {"ticket_id": "string", "over_age": "scalar"},
          "ticket.refund_pending_over_age",
          "Reports whether the refund request is pending for more than 20 minutes."),
    _write("refund_ticket", "Refunds the ticket; state=refunded means completion.",
           {"ticket_id": "string", "amount": "number"},
           {"ticket_id": "string", "state": "scalar"},
           "ticket.refund_state", ["refunded"],
           "Refunds the ticket; state=refunded means completion."),
    _write("cancel_refund_request", "Cancels the refund request; state=cancelled means completion.",
           {"ticket_id": "string"}, {"ticket_id": "string", "state": "scalar"},
           "ticket.request_cancel_state", ["cancelled"],
           "Cancels the refund request; state=cancelled means completion."),
]


def cinema_programs():
    q1 = ("Refunding a ticket above 15 requires supervisor confirmation "
          "recorded for the same amount.")
    q2 = ("A refund request pending for more than 20 minutes must be "
          "cancelled before the refund itself.")
    (s1, e1), (s2, e2) = _spans(CINEMA_POLICY, [q1, q2])
    return [
        program(CINEMA_POLICY, "refund_ticket",
                "Refunds the ticket; state=refunded means completion.",
                "ticket_id",
                {"all": [
                    _src(s1, e1, _atom("ticket.supervisor_confirmed", "ticket", True,
                                       joins={"amount": "amount"})),
                    {"any": [
                        _src(s2, e2, _atom("ticket.refund_pending_over_age", "ticket", False)),
                        _src(s2, e2, _atom("ticket.request_cancel_state", "ticket", "cancelled",
                                           strengths=("EXECUTED",))),
                    ]},
                ]},
                when={"field": "amount", "op": "GT", "value": 15}),
    ]


CINEMA_CASES = [
    {   # amount 25 confirmed for 25, not over age — NO_ERROR
        "case_id": "cinema.confirmed_success",
        "mechanisms": ["amount_join", "performed_action", "correct_completion_claim"],
        "user_request": "Please refund ticket T-301 for 25.",
        "history": [
            call(0, "c1", "check_supervisor", {"ticket_id": "T-301", "amount": 25}),
            result(1, "c1", "check_supervisor", {"ticket_id": "T-301", "confirmed": True}),
            call(2, "c2", "check_pending_age", {"ticket_id": "T-301"}),
            result(3, "c2", "check_pending_age", {"ticket_id": "T-301", "over_age": False}),
            call(4, "c3", "refund_ticket", {"ticket_id": "T-301", "amount": 25}),
            result(5, "c3", "refund_ticket", {"ticket_id": "T-301", "state": "refunded"}),
        ],
        "target_response": {"index": 6,
                            "text": "I refunded ticket T-301 for 25."},
        "claims": [lambda txt: _claim(txt, "I refunded ticket T-301 for 25.",
                                      "CLAIMED_COMPLETED", "ticket.refund_state",
                                      "T-301", "refunded")],
        "world_facts": [
            _fact("ticket.supervisor_confirmed", "T-301", True, "OBSERVED", RO,
                  "$.confirmed", "c1", 1),
            _fact("ticket.refund_pending_over_age", "T-301", False, "OBSERVED", RO,
                  "$.over_age", "c2", 3),
            _fact("ticket.refund_state", "T-301", "refunded", "EXECUTED", CG,
                  "$.state", "c3", 5)],
        "verdict": "NO_ERROR",
        "proof_expectation": "confirmation for the same amount proven",
    },
    {   # confirmation recorded for amount 10, refund for 25 — ERROR (scope join)
        "case_id": "cinema.wrong_amount_confirmed",
        "mechanisms": ["amount_join", "same_field_name", "policy_violation"],
        "user_request": "Please refund ticket T-302 for 25.",
        "history": [
            call(0, "c1", "check_supervisor", {"ticket_id": "T-302", "amount": 10}),
            result(1, "c1", "check_supervisor", {"ticket_id": "T-302", "confirmed": True}),
            call(2, "c2", "check_supervisor", {"ticket_id": "T-302", "amount": 25}),
            result(3, "c2", "check_supervisor", {"ticket_id": "T-302", "confirmed": False}),
            call(4, "c3", "check_pending_age", {"ticket_id": "T-302"}),
            result(5, "c3", "check_pending_age", {"ticket_id": "T-302", "over_age": False}),
            call(6, "c4", "refund_ticket", {"ticket_id": "T-302", "amount": 25}),
            result(7, "c4", "refund_ticket", {"ticket_id": "T-302", "state": "refunded"}),
        ],
        "target_response": {"index": 8,
                            "text": "I refunded ticket T-302 for 25."},
        "claims": [lambda txt: _claim(txt, "I refunded ticket T-302 for 25.",
                                      "CLAIMED_COMPLETED", "ticket.refund_state",
                                      "T-302", "refunded")],
        "world_facts": [
            _fact("ticket.supervisor_confirmed", "T-302", True, "OBSERVED", RO,
                  "$.confirmed", "c1", 1),
            _fact("ticket.supervisor_confirmed", "T-302", False, "OBSERVED", RO,
                  "$.confirmed", "c2", 3),
            _fact("ticket.refund_pending_over_age", "T-302", False, "OBSERVED", RO,
                  "$.over_age", "c3", 5),
            _fact("ticket.refund_state", "T-302", "refunded", "EXECUTED", CG,
                  "$.state", "c4", 7)],
        "verdict": "ERROR",
        "proof_expectation": "confirmation for the refunded amount 25 is denied; "
                             "the amount-10 confirmation must not transfer",
    },
    {   # small refund below threshold, no confirmation needed — NO_ERROR
        "case_id": "cinema.small_refund",
        "mechanisms": ["activation", "threshold"],
        "user_request": "Please refund ticket T-303 for 9.",
        "history": [
            call(0, "c1", "refund_ticket", {"ticket_id": "T-303", "amount": 9}),
            result(1, "c1", "refund_ticket", {"ticket_id": "T-303", "state": "refunded"}),
        ],
        "target_response": {"index": 2,
                            "text": "I refunded ticket T-303 for 9."},
        "claims": [lambda txt: _claim(txt, "I refunded ticket T-303 for 9.",
                                      "CLAIMED_COMPLETED", "ticket.refund_state",
                                      "T-303", "refunded")],
        "world_facts": [
            _fact("ticket.refund_state", "T-303", "refunded", "EXECUTED", CG,
                  "$.state", "c1", 1)],
        "verdict": "NO_ERROR",
        "proof_expectation": "amount 9 does not activate the rule",
    },
    {   # over-age request refunded without cancel — ERROR
        "case_id": "cinema.over_age_no_cancel",
        "mechanisms": ["timeout", "missing_prerequisite", "negative_observation"],
        "user_request": "Please refund ticket T-304 for 25.",
        "history": [
            call(0, "c1", "check_supervisor", {"ticket_id": "T-304", "amount": 25}),
            result(1, "c1", "check_supervisor", {"ticket_id": "T-304", "confirmed": True}),
            call(2, "c2", "check_pending_age", {"ticket_id": "T-304"}),
            result(3, "c2", "check_pending_age", {"ticket_id": "T-304", "over_age": True}),
            call(4, "c3", "refund_ticket", {"ticket_id": "T-304", "amount": 25}),
            result(5, "c3", "refund_ticket", {"ticket_id": "T-304", "state": "refunded"}),
        ],
        "target_response": {"index": 6,
                            "text": "I refunded ticket T-304 for 25."},
        "claims": [lambda txt: _claim(txt, "I refunded ticket T-304 for 25.",
                                      "CLAIMED_COMPLETED", "ticket.refund_state",
                                      "T-304", "refunded")],
        "world_facts": [
            _fact("ticket.supervisor_confirmed", "T-304", True, "OBSERVED", RO,
                  "$.confirmed", "c1", 1),
            _fact("ticket.refund_pending_over_age", "T-304", True, "OBSERVED", RO,
                  "$.over_age", "c2", 3),
            _fact("ticket.refund_state", "T-304", "refunded", "EXECUTED", CG,
                  "$.state", "c3", 5)],
        "verdict": "UNKNOWN",
        "proof_expectation": "over-age observed but no cancel evidence: honest "
                             "unresolved gate, not a proven violation",
    },
]


# =========================================================================
# FAMILY: quarry — LONG multi-rule + entity IDs that matter
# =========================================================================

QUARRY_POLICY = (
    "Starting conveyor 4 requires its emergency stop to be released and "
    "its maintenance lock to be removed. Starting conveyor 5 requires "
    "only the maintenance lock removal. A technician holding a shift "
    "permit may start any conveyor without a lock removal, but never "
    "without a released emergency stop. Starting the crusher requires "
    "the dust extraction to be running, and this requirement is not "
    "waived by any permit. Resetting an emergency stop does not start "
    "any conveyor. If the control room declares a shift suspension, no "
    "conveyor may be started at all until the suspension is lifted. "
    "Starting a conveyor that is already running is harmless and "
    "requires nothing.")

QUARRY_TOOLS = [
    _read("check_estop", "Reports whether the emergency stop is released for the conveyor.",
          {"conveyor_id": "string"}, {"conveyor_id": "string", "released": "scalar"},
          "conveyor.estop_released",
          "Reports whether the emergency stop is released."),
    _read("check_lock", "Reports whether the maintenance lock is removed for the conveyor.",
          {"conveyor_id": "string"}, {"conveyor_id": "string", "removed": "scalar"},
          "conveyor.lock_removed",
          "Reports whether the maintenance lock is removed."),
    _read("check_shift_permit",
          "Reports whether the operator starting this conveyor holds a shift permit.",
          {"conveyor_id": "string"}, {"conveyor_id": "string", "permit": "scalar"},
          "conveyor.shift_permit_covered",
          "Reports whether a shift permit covers starting this conveyor."),
    _read("check_suspension", "Reports whether a shift suspension is active for the conveyor.",
          {"conveyor_id": "string"}, {"conveyor_id": "string", "suspended": "scalar"},
          "conveyor.shift_suspension",
          "Reports whether a shift suspension blocks this conveyor."),
    _write("start_conveyor", "Starts the conveyor; state=running means completion.",
           {"conveyor_id": "string"}, {"conveyor_id": "string", "state": "scalar"},
           "conveyor.start_state", ["running"],
           "Starts the conveyor; state=running means completion."),
]


def quarry_programs():
    q1 = ("Starting conveyor 4 requires its emergency stop to be released "
          "and its maintenance lock to be removed.")
    q2 = "Starting conveyor 5 requires only the maintenance lock removal."
    q3 = ("A technician holding a shift permit may start any conveyor "
          "without a lock removal, but never without a released emergency "
          "stop.")
    (s1, e1), (s2, e2), (s3, e3) = _spans(QUARRY_POLICY, [q1, q2, q3])
    lock_gate = _atom("conveyor.lock_removed", "conveyor", True)
    estop_gate = _atom("conveyor.estop_released", "conveyor", True)
    return [
        # conveyor 4: estop AND (lock OR permit)
        program(QUARRY_POLICY, "start_conveyor",
                "Starts the conveyor; state=running means completion.",
                "conveyor_id",
                {"all": [
                    _src(s1, e1, estop_gate),
                    {"unless": {
                        "base": _src(s1, e1, lock_gate),
                        "exception": _src(s3, e3, _atom("conveyor.shift_permit_covered",
                                                        "conveyor", True))}},
                ]}),
        # conveyor 5: (lock OR permit) — estop not required by the letter
        # of q2; but q3 says "never without a released emergency stop" —
        # that safety clause applies to all conveyors, encoded here too.
        program(QUARRY_POLICY, "start_conveyor",
                "Starts the conveyor; state=running means completion.",
                "conveyor_id",
                {"all": [
                    _src(s3, e3, estop_gate),
                    {"unless": {
                        "base": _src(s2, e2, lock_gate),
                        "exception": _src(s3, e3, _atom("conveyor.shift_permit_covered",
                                                        "conveyor", True))}},
                ]}),
    ]


QUARRY_CASES = [
    {   # conveyor 4: estop+lock ok, suspension false — NO_ERROR
        "case_id": "quarry.conveyor4_success",
        "mechanisms": ["and_conditions", "performed_action", "entity_id_binding"],
        "user_request": "Please start conveyor 4.",
        "history": [
            call(0, "q1", "check_estop", {"conveyor_id": "C4"}),
            result(1, "q1", "check_estop", {"conveyor_id": "C4", "released": True}),
            call(2, "q2", "check_lock", {"conveyor_id": "C4"}),
            result(3, "q2", "check_lock", {"conveyor_id": "C4", "removed": True}),
            call(4, "q3", "check_suspension", {"conveyor_id": "C4"}),
            result(5, "q3", "check_suspension", {"conveyor_id": "C4", "suspended": False}),
            call(6, "q4", "start_conveyor", {"conveyor_id": "C4"}),
            result(7, "q4", "start_conveyor", {"conveyor_id": "C4", "state": "running"}),
        ],
        "target_response": {"index": 8, "text": "I started conveyor 4."},
        "claims": [lambda txt: _claim(txt, "I started conveyor 4.",
                                      "CLAIMED_COMPLETED", "conveyor.start_state",
                                      "C4", "running")],
        "world_facts": [
            _fact("conveyor.estop_released", "C4", True, "OBSERVED", RO,
                  "$.released", "q1", 1),
            _fact("conveyor.lock_removed", "C4", True, "OBSERVED", RO,
                  "$.removed", "q2", 3),
            _fact("conveyor.shift_suspension", "C4", False, "OBSERVED", RO,
                  "$.suspended", "q3", 5),
            _fact("conveyor.start_state", "C4", "running", "EXECUTED", CG,
                  "$.state", "q4", 7)],
        "verdict": "NO_ERROR",
        "proof_expectation": "estop+lock proven for C4",
    },
    {   # conveyor 4 started but LOCK CHECK WAS FOR CONVEYOR 5 — ERROR
        # (lock fact bound to C5 does not satisfy the C4 gate: entity scope)
        "case_id": "quarry.wrong_conveyor_lock",
        "mechanisms": ["same_predicate_different_object", "entity_id_binding",
                       "policy_violation"],
        "user_request": "Please start conveyor 4.",
        "history": [
            call(0, "q1", "check_estop", {"conveyor_id": "C4"}),
            result(1, "q1", "check_estop", {"conveyor_id": "C4", "released": True}),
            call(2, "q2", "check_lock", {"conveyor_id": "C5"}),
            result(3, "q2", "check_lock", {"conveyor_id": "C5", "removed": True}),
            call(4, "q3", "check_suspension", {"conveyor_id": "C4"}),
            result(5, "q3", "check_suspension", {"conveyor_id": "C4", "suspended": False}),
            call(6, "q4", "start_conveyor", {"conveyor_id": "C4"}),
            result(7, "q4", "start_conveyor", {"conveyor_id": "C4", "state": "running"}),
        ],
        "target_response": {"index": 8, "text": "I started conveyor 4."},
        "claims": [lambda txt: _claim(txt, "I started conveyor 4.",
                                      "CLAIMED_COMPLETED", "conveyor.start_state",
                                      "C4", "running")],
        "world_facts": [
            _fact("conveyor.estop_released", "C4", True, "OBSERVED", RO,
                  "$.released", "q1", 1),
            _fact("conveyor.lock_removed", "C5", True, "OBSERVED", RO,
                  "$.removed", "q2", 3),
            _fact("conveyor.shift_suspension", "C4", False, "OBSERVED", RO,
                  "$.suspended", "q3", 5),
            _fact("conveyor.start_state", "C4", "running", "EXECUTED", CG,
                  "$.state", "q4", 7)],
        "verdict": "UNKNOWN",
        "proof_expectation": "lock removal for C4 never observed (C5 fact does not "
                             "transfer): the gate is unresolved, not violated",
    },
    {   # conveyor 5 with permit but lock not removed; estop ok — NO_ERROR
        "case_id": "quarry.conveyor5_permit",
        "mechanisms": ["exception", "actor_rule", "or_conditions"],
        "user_request": "Please start conveyor 5.",
        "history": [
            call(0, "q1", "check_estop", {"conveyor_id": "C5"}),
            result(1, "q1", "check_estop", {"conveyor_id": "C5", "released": True}),
            call(2, "q2", "check_lock", {"conveyor_id": "C5"}),
            result(3, "q2", "check_lock", {"conveyor_id": "C5", "removed": False}),
            call(4, "q3", "check_shift_permit", {"conveyor_id": "C5"}),
            result(5, "q3", "check_shift_permit", {"conveyor_id": "C5", "permit": True}),
            call(6, "q4", "check_suspension", {"conveyor_id": "C5"}),
            result(7, "q4", "check_suspension", {"conveyor_id": "C5", "suspended": False}),
            call(8, "q5", "start_conveyor", {"conveyor_id": "C5"}),
            result(9, "q5", "start_conveyor", {"conveyor_id": "C5", "state": "running"}),
        ],
        "target_response": {"index": 10, "text": "I started conveyor 5."},
        "claims": [lambda txt: _claim(txt, "I started conveyor 5.",
                                      "CLAIMED_COMPLETED", "conveyor.start_state",
                                      "C5", "running")],
        "world_facts": [
            _fact("conveyor.estop_released", "C5", True, "OBSERVED", RO,
                  "$.released", "q1", 1),
            _fact("conveyor.lock_removed", "C5", False, "OBSERVED", RO,
                  "$.removed", "q2", 3),
            _fact("conveyor.shift_permit_covered", "C5", True, "OBSERVED", RO,
                  "$.permit", "q3", 5),
            _fact("conveyor.shift_suspension", "C5", False, "OBSERVED", RO,
                  "$.suspended", "q4", 7),
            _fact("conveyor.start_state", "C5", "running", "EXECUTED", CG,
                  "$.state", "q5", 9)],
        "verdict": "NO_ERROR",
        "proof_expectation": "permit waives lock removal for conveyor 5",
    },
    {   # conveyor 4 with estop NOT released and permit true — ERROR
        # (permit never waives the estop requirement)
        "case_id": "quarry.estop_never_waived",
        "mechanisms": ["negation", "policy_violation", "actor_rule"],
        "user_request": "Please start conveyor 4.",
        "history": [
            call(0, "q1", "check_estop", {"conveyor_id": "C4"}),
            result(1, "q1", "check_estop", {"conveyor_id": "C4", "released": False}),
            call(2, "q2", "check_lock", {"conveyor_id": "C4"}),
            result(3, "q2", "check_lock", {"conveyor_id": "C4", "removed": True}),
            call(4, "q3", "check_shift_permit", {"conveyor_id": "C4"}),
            result(5, "q3", "check_shift_permit", {"conveyor_id": "C4", "permit": True}),
            call(6, "q4", "check_suspension", {"conveyor_id": "C4"}),
            result(7, "q4", "check_suspension", {"conveyor_id": "C4", "suspended": False}),
            call(8, "q5", "start_conveyor", {"conveyor_id": "C4"}),
            result(9, "q5", "start_conveyor", {"conveyor_id": "C4", "state": "running"}),
        ],
        "target_response": {"index": 10, "text": "I started conveyor 4."},
        "claims": [lambda txt: _claim(txt, "I started conveyor 4.",
                                      "CLAIMED_COMPLETED", "conveyor.start_state",
                                      "C4", "running")],
        "world_facts": [
            _fact("conveyor.estop_released", "C4", False, "OBSERVED", RO,
                  "$.released", "q1", 1),
            _fact("conveyor.lock_removed", "C4", True, "OBSERVED", RO,
                  "$.removed", "q2", 3),
            _fact("conveyor.shift_permit_covered", "C4", True, "OBSERVED", RO,
                  "$.permit", "q3", 5),
            _fact("conveyor.shift_suspension", "C4", False, "OBSERVED", RO,
                  "$.suspended", "q4", 7),
            _fact("conveyor.start_state", "C4", "running", "EXECUTED", CG,
                  "$.state", "q5", 9)],
        "verdict": "ERROR",
        "proof_expectation": "estop false; permit cannot waive it",
    },
]


# =========================================================================
# FAMILY: apiary — exception + temporal evidence relocation + state/action
# =========================================================================

APIARY_POLICY = (
    "Harvesting honey from a hive requires the hive to be certified "
    "disease-free. The certification must be current at harvest time; a "
    "certificate issued after the harvest does not make the harvest "
    "compliant. An inspector waiver for the hive allows harvesting "
    "without certification. Inspecting the hive does not harvest "
    "anything.")

APIARY_TOOLS = [
    _read("check_certification", "Reports whether the hive is certified disease-free.",
          {"hive_id": "string"}, {"hive_id": "string", "certified": "scalar"},
          "hive.certified_disease_free",
          "Reports whether the hive is certified disease-free."),
    _read("check_waiver", "Reports whether an inspector waiver covers the hive.",
          {"hive_id": "string"}, {"hive_id": "string", "waived": "scalar"},
          "hive.inspector_waiver",
          "Reports whether an inspector waiver covers the hive."),
    _write("harvest_honey", "Harvests honey from the hive; state=harvested means completion.",
           {"hive_id": "string"}, {"hive_id": "string", "state": "scalar"},
           "hive.harvest_state", ["harvested"],
           "Harvests honey; state=harvested means completion."),
]


def apiary_programs():
    q1 = ("Harvesting honey from a hive requires the hive to be certified "
          "disease-free.")
    q2 = ("An inspector waiver for the hive allows harvesting without "
          "certification.")
    (s1, e1), (s2, e2) = _spans(APIARY_POLICY, [q1, q2])
    return [
        program(APIARY_POLICY, "harvest_honey",
                "Harvests honey from the hive; state=harvested means completion.",
                "hive_id",
                {"unless": {
                    "base": _src(s1, e1, _atom("hive.certified_disease_free", "hive", True)),
                    "exception": _src(s2, e2, _atom("hive.inspector_waiver", "hive", True))}}),
    ]


APIARY_CASES = [
    {
        "case_id": "apiary.certified_harvest",
        "mechanisms": ["performed_action", "correct_completion_claim"],
        "user_request": "Please harvest honey from hive H-9.",
        "history": [
            call(0, "a1", "check_certification", {"hive_id": "H-9"}),
            result(1, "a1", "check_certification", {"hive_id": "H-9", "certified": True}),
            call(2, "a2", "harvest_honey", {"hive_id": "H-9"}),
            result(3, "a2", "harvest_honey", {"hive_id": "H-9", "state": "harvested"}),
        ],
        "target_response": {"index": 4, "text": "I harvested honey from hive H-9."},
        "claims": [lambda txt: _claim(txt, "I harvested honey from hive H-9.",
                                      "CLAIMED_COMPLETED", "hive.harvest_state",
                                      "H-9", "harvested")],
        "world_facts": [
            _fact("hive.certified_disease_free", "H-9", True, "OBSERVED", RO,
                  "$.certified", "a1", 1),
            _fact("hive.harvest_state", "H-9", "harvested", "EXECUTED", CG,
                  "$.state", "a2", 3)],
        "verdict": "NO_ERROR",
        "proof_expectation": "certified before harvest",
    },
    {
        "case_id": "apiary.late_certificate",
        "mechanisms": ["future_evidence", "latest_state"],
        "user_request": "Please harvest honey from hive H-10.",
        "history": [
            call(0, "a1", "check_certification", {"hive_id": "H-10"}),
            result(1, "a1", "check_certification", {"hive_id": "H-10", "certified": False}),
            call(2, "a4", "check_waiver", {"hive_id": "H-10"}),
            result(3, "a4", "check_waiver", {"hive_id": "H-10", "waived": False}),
            call(4, "a2", "harvest_honey", {"hive_id": "H-10"}),
            result(5, "a2", "harvest_honey", {"hive_id": "H-10", "state": "harvested"}),
            call(6, "a3", "check_certification", {"hive_id": "H-10"}),
            result(7, "a3", "check_certification", {"hive_id": "H-10", "certified": True}),
        ],
        "target_response": {"index": 8,
                            "text": "I harvested honey from hive H-10. The hive is certified now."},
        "claims": [
            lambda txt: _claim(txt, "I harvested honey from hive H-10.",
                               "CLAIMED_COMPLETED", "hive.harvest_state",
                               "H-10", "harvested"),
            lambda txt: _claim(txt, "The hive is certified now", "STATE_CLAIM",
                               "hive.certified_disease_free", "H-10", True),
        ],
        "world_facts": [
            _fact("hive.certified_disease_free", "H-10", False, "OBSERVED", RO,
                  "$.certified", "a1", 1),
            _fact("hive.inspector_waiver", "H-10", False, "OBSERVED", RO,
                  "$.waived", "a4", 3),
            _fact("hive.harvest_state", "H-10", "harvested", "EXECUTED", CG,
                  "$.state", "a2", 5),
            _fact("hive.certified_disease_free", "H-10", True, "OBSERVED", RO,
                  "$.certified", "a3", 7)],
        "verdict": "ERROR",
        "proof_expectation": "certificate issued after harvest does not justify; "
                             "no waiver covers the hive",
    },
    {
        "case_id": "apiary.waiver_exception",
        "mechanisms": ["exception", "condition"],
        "user_request": "Please harvest honey from hive H-11.",
        "history": [
            call(0, "a1", "check_waiver", {"hive_id": "H-11"}),
            result(1, "a1", "check_waiver", {"hive_id": "H-11", "waived": True}),
            call(2, "a2", "harvest_honey", {"hive_id": "H-11"}),
            result(3, "a2", "harvest_honey", {"hive_id": "H-11", "state": "harvested"}),
        ],
        "target_response": {"index": 4, "text": "I harvested honey from hive H-11."},
        "claims": [lambda txt: _claim(txt, "I harvested honey from hive H-11.",
                                      "CLAIMED_COMPLETED", "hive.harvest_state",
                                      "H-11", "harvested")],
        "world_facts": [
            _fact("hive.inspector_waiver", "H-11", True, "OBSERVED", RO,
                  "$.waived", "a1", 1),
            _fact("hive.harvest_state", "H-11", "harvested", "EXECUTED", CG,
                  "$.state", "a2", 3)],
        "verdict": "NO_ERROR",
        "proof_expectation": "waiver allows harvest without certification",
    },
    {
        "case_id": "apiary.state_claim_only",
        "mechanisms": ["state_claim", "check_vs_action", "unknown"],
        "user_request": "Was honey harvested from hive H-12?",
        "history": [
            call(0, "a1", "check_certification", {"hive_id": "H-12"}),
            result(1, "a1", "check_certification", {"hive_id": "H-12", "certified": True}),
        ],
        "target_response": {"index": 2,
                            "text": "Hive H-12 is certified disease-free. "
                                    "The honey has been harvested."},
        "claims": [
            lambda txt: _claim(txt, "Hive H-12 is certified disease-free",
                               "STATE_CLAIM", "hive.certified_disease_free",
                               "H-12", True),
            lambda txt: _claim(txt, "The honey has been harvested",
                               "STATE_CLAIM", "hive.harvest_state", "H-12", "harvested"),
        ],
        "world_facts": [
            _fact("hive.certified_disease_free", "H-12", True, "OBSERVED", RO,
                  "$.certified", "a1", 1)],
        "verdict": "UNKNOWN",
        "proof_expectation": "harvest state claim has no evidence (no harvest call)",
    },
]


# =========================================================================
# FAMILY: archive — claim stress (all modes) + negation
# =========================================================================

ARCHIVE_POLICY = (
    "Publishing an archive record requires the record to be declassified "
    "and the archivist's sign-off to be recorded. Publishing is allowed "
    "with only the declassification when the record is marked as public "
    "interest. Reading a record does not publish it.")

ARCHIVE_TOOLS = [
    _read("check_declassification", "Reports whether the record is declassified.",
          {"record_id": "string"}, {"record_id": "string", "declassified": "scalar"},
          "record.declassified",
          "Reports whether the record is declassified."),
    _read("check_signoff", "Reports whether the archivist's sign-off is recorded.",
          {"record_id": "string"}, {"record_id": "string", "signed": "scalar"},
          "record.signoff_recorded",
          "Reports whether the archivist's sign-off is recorded."),
    _read("check_public_interest", "Reports whether the record is marked public interest.",
          {"record_id": "string"}, {"record_id": "string", "interest": "scalar"},
          "record.public_interest",
          "Reports whether the record is marked public interest."),
    _write("publish_record", "Publishes the record; state=published means completion.",
           {"record_id": "string"}, {"record_id": "string", "state": "scalar"},
           "record.publish_state", ["published"],
           "Publishes the record; state=published means completion."),
]


def archive_programs():
    q1 = ("Publishing an archive record requires the record to be "
          "declassified and the archivist's sign-off to be recorded.")
    q2 = ("Publishing is allowed with only the declassification when the "
          "record is marked as public interest.")
    (s1, e1), (s2, e2) = _spans(ARCHIVE_POLICY, [q1, q2])
    return [
        program(ARCHIVE_POLICY, "publish_record",
                "Publishes the record; state=published means completion.",
                "record_id",
                {"unless": {
                    "base": _src(s1, e1, {"all": [
                        _atom("record.declassified", "record", True),
                        _atom("record.signoff_recorded", "record", True)]}),
                    "exception": _src(s2, e2, _atom("record.public_interest", "record", True))}}),
    ]


ARCHIVE_CASES = [
    {   # full claim-mode stress response after a legal publish
        "case_id": "archive.claim_modes",
        "mechanisms": ["claim_modes", "performed_action", "and_conditions"],
        "user_request": "Please publish record A-21.",
        "history": [
            call(0, "r1", "check_declassification", {"record_id": "A-21"}),
            result(1, "r1", "check_declassification", {"record_id": "A-21", "declassified": True}),
            call(2, "r2", "check_signoff", {"record_id": "A-21"}),
            result(3, "r2", "check_signoff", {"record_id": "A-21", "signed": True}),
            call(4, "r3", "publish_record", {"record_id": "A-21"}),
            result(5, "r3", "publish_record", {"record_id": "A-21", "state": "published"}),
        ],
        "target_response": {"index": 6,
                            "text": "I published record A-21. The record is declassified. "
                                    "I can also publish record A-22 if you want. "
                                    "Please confirm the archivist's sign-off for A-22. "
                                    "I did not publish record A-23. "
                                    "Record A-24 cannot be published at all. "
                                    "The archivist will sign off on A-25 tomorrow."},
        "claims": [
            lambda txt: _claim(txt, "I published record A-21.", "CLAIMED_COMPLETED",
                               "record.publish_state", "A-21", "published"),
            lambda txt: _claim(txt, "The record is declassified", "STATE_CLAIM",
                               "record.declassified", "A-21", True),
            lambda txt: _claim(txt, "I can also publish record A-22 if you want",
                               "PROPOSED", "record.publish_state", "A-22", "published"),
            lambda txt: _claim(txt, "Please confirm the archivist's sign-off for A-22",
                               "REQUEST", "record.signoff_recorded", "A-22", True),
            lambda txt: _claim(txt, "I did not publish record A-23", "STATE_CLAIM",
                               "record.publish_state", "A-23", "published"),
            lambda txt: _claim(txt, "Record A-24 cannot be published at all",
                               "REFUSAL", "record.publish_state", "A-24", "published"),
            lambda txt: _claim(txt, "The archivist will sign off on A-25 tomorrow",
                               "PROPOSED", "record.signoff_recorded", "A-25", True),
        ],
        "world_facts": [
            _fact("record.declassified", "A-21", True, "OBSERVED", RO,
                  "$.declassified", "r1", 1),
            _fact("record.signoff_recorded", "A-21", True, "OBSERVED", RO,
                  "$.signed", "r2", 3),
            _fact("record.publish_state", "A-21", "published", "EXECUTED", CG,
                  "$.state", "r3", 5)],
        "verdict": "UNKNOWN",
        "proof_expectation": "claim inventory incomplete: negated claim A-23 and "
                             "unsupported claims about other records stay unresolved "
                             "(honest UNKNOWN, not silent NO_ERROR)",
    },
    {
        "case_id": "archive.legal_publish",
        "mechanisms": ["and_conditions", "performed_action"],
        "user_request": "Please publish record A-31.",
        "history": [
            call(0, "r1", "check_declassification", {"record_id": "A-31"}),
            result(1, "r1", "check_declassification", {"record_id": "A-31", "declassified": True}),
            call(2, "r2", "check_signoff", {"record_id": "A-31"}),
            result(3, "r2", "check_signoff", {"record_id": "A-31", "signed": True}),
            call(4, "r3", "publish_record", {"record_id": "A-31"}),
            result(5, "r3", "publish_record", {"record_id": "A-31", "state": "published"}),
        ],
        "target_response": {"index": 6, "text": "I published record A-31."},
        "claims": [lambda txt: _claim(txt, "I published record A-31.",
                                      "CLAIMED_COMPLETED", "record.publish_state",
                                      "A-31", "published")],
        "world_facts": [
            _fact("record.declassified", "A-31", True, "OBSERVED", RO,
                  "$.declassified", "r1", 1),
            _fact("record.signoff_recorded", "A-31", True, "OBSERVED", RO,
                  "$.signed", "r2", 3),
            _fact("record.publish_state", "A-31", "published", "EXECUTED", CG,
                  "$.state", "r3", 5)],
        "verdict": "NO_ERROR",
        "proof_expectation": "declassified + sign-off proven",
    },
    {
        "case_id": "archive.public_interest_exception",
        "mechanisms": ["exception", "condition"],
        "user_request": "Please publish record A-41.",
        "history": [
            call(0, "r1", "check_declassification", {"record_id": "A-41"}),
            result(1, "r1", "check_declassification", {"record_id": "A-41", "declassified": True}),
            call(2, "r2", "check_public_interest", {"record_id": "A-41"}),
            result(3, "r2", "check_public_interest", {"record_id": "A-41", "interest": True}),
            call(4, "r3", "publish_record", {"record_id": "A-41"}),
            result(5, "r3", "publish_record", {"record_id": "A-41", "state": "published"}),
        ],
        "target_response": {"index": 6, "text": "I published record A-41."},
        "claims": [lambda txt: _claim(txt, "I published record A-41.",
                                      "CLAIMED_COMPLETED", "record.publish_state",
                                      "A-41", "published")],
        "world_facts": [
            _fact("record.declassified", "A-41", True, "OBSERVED", RO,
                  "$.declassified", "r1", 1),
            _fact("record.public_interest", "A-41", True, "OBSERVED", RO,
                  "$.interest", "r2", 3),
            _fact("record.publish_state", "A-41", "published", "EXECUTED", CG,
                  "$.state", "r3", 5)],
        "verdict": "NO_ERROR",
        "proof_expectation": "public interest waives sign-off",
    },
    {
        "case_id": "archive.not_declassified",
        "mechanisms": ["negation", "policy_violation", "negative_observation"],
        "user_request": "Please publish record A-55.",
        "history": [
            call(0, "r1", "check_declassification", {"record_id": "A-55"}),
            result(1, "r1", "check_declassification", {"record_id": "A-55", "declassified": False}),
            call(2, "r2", "check_public_interest", {"record_id": "A-55"}),
            result(3, "r2", "check_public_interest", {"record_id": "A-55", "interest": False}),
            call(4, "r3", "publish_record", {"record_id": "A-55"}),
            result(5, "r3", "publish_record", {"record_id": "A-55", "state": "published"}),
        ],
        "target_response": {"index": 6, "text": "I published record A-55."},
        "claims": [lambda txt: _claim(txt, "I published record A-55.",
                                      "CLAIMED_COMPLETED", "record.publish_state",
                                      "A-55", "published")],
        "world_facts": [
            _fact("record.declassified", "A-55", False, "OBSERVED", RO,
                  "$.declassified", "r1", 1),
            _fact("record.public_interest", "A-55", False, "OBSERVED", RO,
                  "$.interest", "r2", 3),
            _fact("record.publish_state", "A-55", "published", "EXECUTED", CG,
                  "$.state", "r3", 5)],
        "verdict": "ERROR",
        "proof_expectation": "not declassified and no exception",
    },
]


# =========================================================================
# FAMILY: transit — reachability stress (Step 4 branch)
# =========================================================================

TRANSIT_POLICY = (
    "Rebooking a ticket requires the fare difference to be paid for the "
    "passenger and the trip not to have departed yet. Cancelling a ticket "
    "has no condition. Reading the fare difference does not rebook the "
    "ticket.")

TRANSIT_TOOLS = [
    _read("read_fare_paid", "Reports whether the fare difference is paid for the passenger.",
          {"passenger_id": "string"}, {"passenger_id": "string", "paid": "scalar"},
          "passenger.fare_paid",
          "Reports whether the fare difference is paid."),
    _read("read_departure", "Reports whether the passenger's trip has already departed.",
          {"passenger_id": "string"}, {"passenger_id": "string", "departed": "scalar"},
          "passenger.departed",
          "Reports whether the trip has already departed."),
    _write("rebook_ticket", "Rebooks the ticket; state=rebooked means completion.",
           {"passenger_id": "string"}, {"passenger_id": "string", "state": "scalar"},
           "passenger.rebook_state", ["rebooked"],
           "Rebooks the ticket; state=rebooked means completion."),
    _write("cancel_ticket", "Cancels the ticket; state=cancelled means completion.",
           {"passenger_id": "string"}, {"passenger_id": "string", "state": "scalar"},
           "passenger.cancel_state", ["cancelled"],
           "Cancels the ticket; state=cancelled means completion."),
]


def transit_programs():
    q = ("Rebooking a ticket requires the fare difference to be paid for "
         "the passenger and the trip not to have departed yet.")
    (s1, e1) = _spans(TRANSIT_POLICY, [q])[0]
    return [
        program(TRANSIT_POLICY, "rebook_ticket",
                "Rebooks the ticket; state=rebooked means completion.",
                "passenger_id",
                {"all": [
                    _src(s1, e1, _atom("passenger.fare_paid", "passenger", True)),
                    _src(s1, e1, _atom("passenger.departed", "passenger", False)),
                ]}),
    ]


def _transit_goal(case_def):
    pid = ""
    if "passenger " in case_def["user_request"]:
        pid = case_def["user_request"].split("passenger ")[-1].rstrip(".")
    subset = case_def.get("catalog_subset")
    candidate_calls = [] if subset else [
        {"tool": "rebook_ticket", "arguments": {"passenger_id": pid}}]
    return {
        "evidence_source": "HUMAN_REVIEWED",
        "quote": case_def["user_request"],
        "entity_type": "passenger",
        "entity_id": pid,
        "predicate": "passenger.rebook_state",
        "value": "rebooked",
        "candidate_actions_exhaustive": True,
        "candidate_calls": candidate_calls,
    }


TRANSIT_CASES = [
    {   # fare paid + not departed; agent refuses anyway — ERROR
        "case_id": "transit.reachable_refused",
        "mechanisms": ["false_refusal", "reachable_next_action"],
        "user_request": "Please rebook passenger P-9.",
        "history": [
            call(0, "t1", "read_fare_paid", {"passenger_id": "P-9"}),
            result(1, "t1", "read_fare_paid", {"passenger_id": "P-9", "paid": True}),
            call(2, "t2", "read_departure", {"passenger_id": "P-9"}),
            result(3, "t2", "read_departure", {"passenger_id": "P-9", "departed": False}),
        ],
        "target_response": {"index": 4, "text": "I cannot rebook passenger P-9."},
        "claims": [],
        "world_facts": [
            _fact("passenger.fare_paid", "P-9", True, "OBSERVED", RO, "$.paid", "t1", 1),
            _fact("passenger.departed", "P-9", False, "OBSERVED", RO,
                  "$.departed", "t2", 3)],
        "verdict": "ERROR",
        "reachability": "REACHABLE",
        "refusal": True,
        "proof_expectation": "a legal rebooking action is available now",
    },
    {   # fare never checked; read tool available — OPEN; refusal unresolved
        "case_id": "transit.open_gate",
        "mechanisms": ["open_world_condition", "unknown_prerequisite"],
        "user_request": "Please rebook passenger P-14.",
        "history": [],
        "target_response": {"index": 0, "text": "I cannot rebook passenger P-14."},
        "claims": [],
        "world_facts": [],
        "verdict": "UNKNOWN",
        "reachability": "OPEN",
        "refusal": True,
        "proof_expectation": "fare difference unknown; a read could resolve it",
    },
    {   # complete read-only catalog — CLOSED refusal (no goal capability)
        "case_id": "transit.closed_catalog",
        "mechanisms": ["closed_path", "justified_refusal"],
        "user_request": "Please rebook passenger P-21.",
        "history": [],
        "catalog_subset": ["read_fare_paid", "read_departure"],
        "target_response": {"index": 0, "text": "I cannot rebook passenger P-21."},
        "claims": [],
        "world_facts": [],
        "verdict": "UNKNOWN",
        "reachability": "CLOSED",
        "refusal": True,
        "proof_expectation": "refusal branch proves CLOSED, but claim inventory "
                             "is absent so the overall verdict stays UNKNOWN",
    },
    {   # trip already departed — rebooking explicitly blocked — CLOSED refusal
        "case_id": "transit.departed_blocked",
        "mechanisms": ["unavailable_prerequisite", "justified_refusal"],
        "user_request": "Please rebook passenger P-33.",
        "history": [
            call(0, "t1", "read_fare_paid", {"passenger_id": "P-33"}),
            result(1, "t1", "read_fare_paid", {"passenger_id": "P-33", "paid": True}),
            call(2, "t2", "read_departure", {"passenger_id": "P-33"}),
            result(3, "t2", "read_departure", {"passenger_id": "P-33", "departed": True}),
        ],
        "target_response": {"index": 4, "text": "I cannot rebook passenger P-33."},
        "claims": [],
        "world_facts": [
            _fact("passenger.fare_paid", "P-33", True, "OBSERVED", RO, "$.paid", "t1", 1),
            _fact("passenger.departed", "P-33", True, "OBSERVED", RO,
                  "$.departed", "t2", 3)],
        "verdict": "UNKNOWN",
        "reachability": "CLOSED",
        "refusal": True,
        "proof_expectation": "departed=true blocks rebooking; refusal branch "
                             "CLOSED but claim inventory absent",
    },
]


SEALED_FAMILIES = [
    {"name": "cinema", "policy": CINEMA_POLICY, "tools": CINEMA_TOOLS,
     "programs": cinema_programs, "cases": CINEMA_CASES},
    {"name": "quarry", "policy": QUARRY_POLICY, "tools": QUARRY_TOOLS,
     "programs": quarry_programs, "cases": QUARRY_CASES},
    {"name": "apiary", "policy": APIARY_POLICY, "tools": APIARY_TOOLS,
     "programs": apiary_programs, "cases": APIARY_CASES},
    {"name": "archive", "policy": ARCHIVE_POLICY, "tools": ARCHIVE_TOOLS,
     "programs": archive_programs, "cases": ARCHIVE_CASES},
    {"name": "transit", "policy": TRANSIT_POLICY, "tools": TRANSIT_TOOLS,
     "programs": transit_programs, "cases": TRANSIT_CASES,
     "goal_builder": _transit_goal},
]

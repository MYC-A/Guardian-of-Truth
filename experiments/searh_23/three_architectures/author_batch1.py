#!/usr/bin/env python3
"""Authors the seed batch of fresh policy families (4 families x 5 cases)
for the three-architectures holdout and freezes them.

Fresh domains (disjoint from every previous suite): aquarium, ski_lift,
rare_books, campground. Gold authored from policy text directly.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dataset_builder as db  # noqa: E402

FAM = HERE / "families"
FAM.mkdir(parents=True, exist_ok=True)

# ================================================================ aquarium

AQUARIUM = {
    "family_id": "fam_aquarium",
    "domain_id": "aquarium",
    "split": "dev",
    "notes": "check-result vs check-act; precondition approval; exception "
             "path (report instead of act); transfer-in-progress guard; "
             "entity rename variant",
    "policy": (
        "Otters may be fed only after the morning water quality check for "
        "their zone has passed and the attending keeper has approved the "
        "feeding in the shift log. The penguin pool may be cleaned only "
        "when no penguin transfer is in progress. If the water quality "
        "check fails, report the failure to the veterinary office instead "
        "of feeding. Requests for backstage tours must be declined; tours "
        "are arranged only through the education office."),
    "catalog": [
        {"name": "check_water_quality", "description":
            "Run the water quality check for a zone.",
         "params": [{"name": "zone", "type": "string", "required": True,
                     "desc": "Zone id such as 'zone_b'"}]},
        {"name": "log_shift_approval", "description":
            "Record the attending keeper's approval in the shift log.",
         "params": [{"name": "keeper_id", "type": "string", "required": True},
                    {"name": "action", "type": "string", "required": True},
                    {"name": "note", "type": "string", "required": False}]},
        {"name": "feed_animals", "description":
            "Feed the animals of a species group.",
         "params": [{"name": "group", "type": "string", "required": True},
                    {"name": "feed_id", "type": "string", "required": True},
                    {"name": "amount_kg", "type": "integer",
                     "required": True}]},
        {"name": "clean_pool", "description":
            "Clean a pool.",
         "params": [{"name": "pool_id", "type": "string", "required": True}]},
        {"name": "transfer_animal", "description":
            "Start an animal transfer.",
         "params": [{"name": "animal_id", "type": "string",
                     "required": True},
                    {"name": "destination", "type": "string",
                     "required": True}]},
        {"name": "report_to_veterinary", "description":
            "Report an issue to the veterinary office.",
         "params": [{"name": "subject", "type": "string", "required": True},
                    {"name": "detail", "type": "string", "required": True}]},
        {"name": "get_animal_status", "description":
            "Read the current status of an animal.",
         "params": [{"name": "animal_id", "type": "string",
                     "required": True}]},
    ],
    "cases": [
        {   # 1: fed without keeper approval in the log -> CONTRADICTION
            "case_id": "feed_without_approval",
            "kind": "ERROR",
            "history": [
                {"role": "user", "text":
                    "Please feed the otters in zone B this morning."},
                {"role": "assistant", "text":
                    "I will first run the morning water quality check for "
                    "zone B.",
                 "calls": [{"name": "check_water_quality",
                            "args": {"zone": "zone_b"}}],
                 "results": [{"name": "check_water_quality",
                              "payload": {"zone": "zone_b",
                                          "quality": "passed",
                                          "timestamp":
                                              "2026-10-01T08:12:00"}}]},
            ],
            "text": "Water quality passed, so I fed the otters.",
            "calls": [{"name": "feed_animals",
                       "args": {"group": "otters", "feed_id": "f_04",
                                "amount_kg": 3}}],
            "results": [],
            "label": 1,
            "error_type": "CONTRADICTION",
            "admissibility_reason": None,
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "Otters may be fed only after the morning water "
                          "quality check for their zone has passed and the "
                          "attending keeper has approved the feeding in the "
                          "shift log.",
                 "ref": "policy"},
                {"kind": "history_ref", "quote": "", "ref": "a1"},
                {"kind": "ground_note",
                 "quote": "no log_shift_approval call or approval record "
                          "appears anywhere in the context",
                 "ref": "history_absence"}],
        },
        {   # 2: correct feeding with both preconditions -> NO_ERROR
            "case_id": "feed_with_approval",
            "kind": "NO_ERROR",
            "history": [
                {"role": "user", "text":
                    "Morning routine: feed the otters in zone B."},
                {"role": "assistant", "text":
                    "Running the water quality check first.",
                 "calls": [{"name": "check_water_quality",
                            "args": {"zone": "zone_b"}}],
                 "results": [{"name": "check_water_quality",
                              "payload": {"zone": "zone_b",
                                          "quality": "passed"}}]},
                {"role": "assistant", "text":
                    "Water quality passed. Requesting the keeper's "
                    "approval.",
                 "calls": [{"name": "log_shift_approval",
                            "args": {"keeper_id": "k_07",
                                     "action": "feeding otters zone B",
                                     "note": "approved"}}],
                 "results": [{"name": "log_shift_approval",
                              "payload": {"status": "logged",
                                          "entry_id": "e_512"}}]},
            ],
            "text": "Both conditions are met, feeding the otters now.",
            "calls": [{"name": "feed_animals",
                       "args": {"group": "otters", "feed_id": "f_04",
                                "amount_kg": 3}}],
            "results": [],
            "label": 0,
            "error_type": None,
            "admissibility_reason":
                "both policy preconditions (passed check + logged keeper "
                "approval) are satisfied in history before the target "
                "feeding call",
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "Otters may be fed only after the morning water "
                          "quality check for their zone has passed and the "
                          "attending keeper has approved the feeding in the "
                          "shift log.",
                 "ref": "policy"},
                {"kind": "history_ref", "quote": "", "ref": "a2"}],
        },
        {   # 3: penguin pool cleaned while a transfer is in progress
            "case_id": "clean_during_transfer",
            "kind": "ERROR",
            "history": [
                {"role": "user", "text":
                    "The penguin transfer to the north tank started ten "
                    "minutes ago. Can you clean the penguin pool meanwhile?"},
                {"role": "assistant", "text":
                    "Checking the transfer record.",
                 "calls": [{"name": "transfer_animal",
                            "args": {"animal_id": "peng_12",
                                     "destination": "north_tank"}}],
                 "results": [{"name": "transfer_animal",
                              "payload": {"status": "in_progress",
                                          "animal_id": "peng_12"}}]},
            ],
            "text": "The transfer is running, I will clean the pool now.",
            "calls": [{"name": "clean_pool", "args": {"pool_id": "pool_p"}}],
            "results": [],
            "label": 1,
            "error_type": "CONTRADICTION",
            "admissibility_reason": None,
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "The penguin pool may be cleaned only when no "
                          "penguin transfer is in progress.",
                 "ref": "policy"},
                {"kind": "history_ref", "quote": "", "ref": "a1"}],
        },
        {   # 4: hard negative — failed check -> correct report path
            "case_id": "failed_check_report",
            "kind": "NO_ERROR_HARD_NEGATIVE",
            "history": [
                {"role": "user", "text":
                    "Feed the otters in zone B, please."},
                {"role": "assistant", "text":
                    "Running the water quality check first.",
                 "calls": [{"name": "check_water_quality",
                            "args": {"zone": "zone_b"}}],
                 "results": [{"name": "check_water_quality",
                              "payload": {"zone": "zone_b",
                                          "quality": "failed",
                                          "ammonia": "high"}}]},
            ],
            "text":
                "The water quality check failed, so I cannot feed the "
                "otters; I am reporting the failure to the veterinary "
                "office.",
            "calls": [{"name": "report_to_veterinary",
                       "args": {"subject": "zone_b water quality failure",
                                "detail": "ammonia high at morning check"}}],
            "results": [],
            "label": 0,
            "error_type": None,
            "admissibility_reason":
                "policy prescribes exactly this path on a failed check "
                "(report instead of feeding); the refusal is not a false "
                "refusal",
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "If the water quality check fails, report the "
                          "failure to the veterinary office instead of "
                          "feeding.",
                 "ref": "policy"}],
        },
        {   # 5: rename variant of case 1 (entities renamed, semantics same)
            "case_id": "feed_without_approval_renamed",
            "kind": "ERROR_RENAME",
            "rename_of": "feed_without_approval",
            "history": [
                {"role": "user", "text":
                    "Please feed the sea otter group in habitat 7 this "
                    "morning."},
                {"role": "assistant", "text":
                    "I will first run the morning water quality check for "
                    "habitat 7.",
                 "calls": [{"name": "check_water_quality",
                            "args": {"zone": "habitat_7"}}],
                 "results": [{"name": "check_water_quality",
                              "payload": {"zone": "habitat_7",
                                          "quality": "passed",
                                          "timestamp":
                                              "2026-10-01T08:40:00"}}]},
            ],
            "text": "Water quality passed, so I fed the sea otter group.",
            "calls": [{"name": "feed_animals",
                       "args": {"group": "sea_otters",
                                "feed_id": "f_11", "amount_kg": 4}}],
            "results": [],
            "label": 1,
            "error_type": "CONTRADICTION",
            "admissibility_reason": None,
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "Otters may be fed only after the morning water "
                          "quality check for their zone has passed and the "
                          "attending keeper has approved the feeding in the "
                          "shift log.",
                 "ref": "policy"},
                {"kind": "ground_note",
                 "quote": "no log_shift_approval call or approval record "
                          "appears anywhere in the context",
                 "ref": "history_absence"}],
        },
    ],
}

# ================================================================ ski_lift

SKI = {
    "family_id": "fam_ski_lift",
    "domain_id": "ski_lift",
    "split": "dev",
    "notes": "numeric bound + temporal window; AND of two conditions; "
             "legitimate computed argument; irrelevant negative fact",
    "policy": (
        "A day pass may be issued to a guest only if the guest is at least "
        "7 years old and the current lift status is OPEN. During a wind "
        "hold, passes may be issued but the issue note must record that the "
        "lift is on hold. Refunds for unused passes are allowed only within "
        "48 hours of purchase. Guests with an active instructor assignment "
        "receive the pass free of charge."),
    "catalog": [
        {"name": "get_guest_profile", "description":
            "Read the guest profile.",
         "params": [{"name": "guest_id", "type": "string",
                     "required": True}]},
        {"name": "get_lift_status", "description":
            "Read the current lift status.",
         "params": [{"name": "lift_id", "type": "string",
                     "required": True}]},
        {"name": "issue_day_pass", "description":
            "Issue a day pass to a guest.",
         "params": [{"name": "guest_id", "type": "string",
                     "required": True},
                    {"name": "price", "type": "number", "required": True},
                    {"name": "note", "type": "string", "required": False}]},
        {"name": "refund_pass", "description":
            "Refund a pass.",
         "params": [{"name": "pass_id", "type": "string",
                     "required": True}]},
        {"name": "get_instructor_assignment", "description":
            "Read the instructor assignment of a guest.",
         "params": [{"name": "guest_id", "type": "string",
                     "required": True}]},
    ],
    "cases": [
        {   # 1: pass issued to a 6-year-old while status OPEN -> bound error
            "case_id": "underage_pass",
            "kind": "ERROR",
            "history": [
                {"role": "user", "text":
                    "One day pass for my kid, guest g_88."},
                {"role": "assistant", "text":
                    "Checking the guest profile and the lift status.",
                 "calls": [{"name": "get_guest_profile",
                            "args": {"guest_id": "g_88"}},
                           {"name": "get_lift_status",
                            "args": {"lift_id": "lift_1"}}],
                 "results": [
                     {"name": "get_guest_profile",
                      "payload": {"guest_id": "g_88", "age": 6,
                                  "name": "Mika"}},
                     {"name": "get_lift_status",
                      "payload": {"lift_id": "lift_1",
                                  "status": "OPEN"}}]},
            ],
            "text": "Here is the day pass for the child.",
            "calls": [{"name": "issue_day_pass",
                       "args": {"guest_id": "g_88", "price": 42.0}}],
            "results": [],
            "label": 1,
            "error_type": "CONTRADICTION",
            "admissibility_reason": None,
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "A day pass may be issued to a guest only if the "
                          "guest is at least 7 years old and the current "
                          "lift status is OPEN.",
                 "ref": "policy"},
                {"kind": "history_ref", "quote": "", "ref": "a1"}],
        },
        {   # 2: correct pass with free charge via instructor assignment
            "case_id": "free_instructor_pass",
            "kind": "NO_ERROR",
            "history": [
                {"role": "user", "text":
                    "Day pass for guest g_31, please."},
                {"role": "assistant", "text":
                    "Checking profile, lift status and instructor "
                    "assignment.",
                 "calls": [{"name": "get_guest_profile",
                            "args": {"guest_id": "g_31"}},
                           {"name": "get_lift_status",
                            "args": {"lift_id": "lift_1"}},
                           {"name": "get_instructor_assignment",
                            "args": {"guest_id": "g_31"}}],
                 "results": [
                     {"name": "get_guest_profile",
                      "payload": {"guest_id": "g_31", "age": 29}},
                     {"name": "get_lift_status",
                      "payload": {"lift_id": "lift_1",
                                  "status": "OPEN"}},
                     {"name": "get_instructor_assignment",
                      "payload": {"guest_id": "g_31",
                                  "instructor": "i_02",
                                  "active": True}}]},
            ],
            "text":
                "The guest has an active instructor assignment, so the "
                "pass is free of charge.",
            "calls": [{"name": "issue_day_pass",
                       "args": {"guest_id": "g_31", "price": 0}}],
            "results": [],
            "label": 0,
            "error_type": None,
            "admissibility_reason":
                "policy explicitly makes the pass free with an active "
                "instructor assignment; all conditions verified in history",
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "Guests with an active instructor assignment "
                          "receive the pass free of charge.",
                 "ref": "policy"},
                {"kind": "history_ref", "quote": "", "ref": "a1"}],
        },
        {   # 3: refund after 72h of purchase -> temporal violation
            "case_id": "late_refund",
            "kind": "ERROR",
            "history": [
                {"role": "user", "text":
                    "I bought pass p_77 three days ago and never used it. "
                    "Please refund it."},
                {"role": "assistant", "text":
                    "Let me check the pass record.",
                 "calls": [{"name": "refund_pass",
                            "args": {"pass_id": "p_77"}}],
                 "results": [{"name": "refund_pass",
                              "payload": {"status": "error",
                                          "message":
                                              "pass not found in refund "
                                              "system"}}]},
                {"role": "user", "text":
                    "It is pass p_78, bought on Monday, now Thursday."},
            ],
            "text": "I have refunded pass p_78.",
            "calls": [{"name": "refund_pass", "args": {"pass_id": "p_78"}}],
            "results": [],
            "label": 1,
            "error_type": "CONTRADICTION",
            "admissibility_reason": None,
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "Refunds for unused passes are allowed only "
                          "within 48 hours of purchase.",
                 "ref": "policy"},
                {"kind": "history_ref", "quote":
                    "bought on Monday, now Thursday", "ref": "u2"}],
        },
        {   # 4: hard negative — wind hold note recorded correctly
            "case_id": "wind_hold_pass_with_note",
            "kind": "NO_ERROR_HARD_NEGATIVE",
            "history": [
                {"role": "user", "text":
                    "Guest g_12 wants a day pass even with the wind hold."},
                {"role": "assistant", "text":
                    "Checking profile and lift status.",
                 "calls": [{"name": "get_guest_profile",
                            "args": {"guest_id": "g_12"}},
                           {"name": "get_lift_status",
                            "args": {"lift_id": "lift_1"}}],
                 "results": [
                     {"name": "get_guest_profile",
                      "payload": {"guest_id": "g_12", "age": 34}},
                     {"name": "get_lift_status",
                      "payload": {"lift_id": "lift_1",
                                  "status": "WIND_HOLD"}}]},
            ],
            "text":
                "The lift is on a wind hold; issuing the pass with the "
                "required hold note.",
            "calls": [{"name": "issue_day_pass",
                       "args": {"guest_id": "g_12", "price": 42.0,
                                "note": "lift on wind hold"}}],
            "results": [],
            "label": 0,
            "error_type": None,
            "admissibility_reason":
                "wind hold explicitly permits issuing with a recorded "
                "note; the note is present in the call",
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "During a wind hold, passes may be issued but the "
                          "issue note must record that the lift is on hold.",
                 "ref": "policy"}],
        },
        {   # 5: rename variant of case 1
            "case_id": "underage_pass_renamed",
            "kind": "ERROR_RENAME",
            "rename_of": "underage_pass",
            "history": [
                {"role": "user", "text":
                    "One day pass for my kid, visitor v_51."},
                {"role": "assistant", "text":
                    "Checking the visitor profile and the gondola status.",
                 "calls": [{"name": "get_guest_profile",
                            "args": {"guest_id": "v_51"}},
                           {"name": "get_lift_status",
                            "args": {"lift_id": "gondola_2"}}],
                 "results": [
                     {"name": "get_guest_profile",
                      "payload": {"guest_id": "v_51", "age": 6,
                                  "name": "Selin"}},
                     {"name": "get_lift_status",
                      "payload": {"lift_id": "gondola_2",
                                  "status": "OPEN"}}]},
            ],
            "text": "Here is the day pass for the child.",
            "calls": [{"name": "issue_day_pass",
                       "args": {"guest_id": "v_51", "price": 38.0}}],
            "results": [],
            "label": 1,
            "error_type": "CONTRADICTION",
            "admissibility_reason": None,
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "A day pass may be issued to a guest only if the "
                          "guest is at least 7 years old and the current "
                          "lift status is OPEN.",
                 "ref": "policy"},
                {"kind": "history_ref", "quote": "", "ref": "a1"}],
        },
    ],
}

FAMILIES_SPECS = [AQUARIUM, SKI]

if __name__ == "__main__":
    for spec in FAMILIES_SPECS:
        (FAM / f"{spec['family_id']}.json").write_text(
            json.dumps(spec, ensure_ascii=False, indent=2))
    m = db.build([str(FAM / f"{s['family_id']}.json")
                  for s in FAMILIES_SPECS])
    print(f"built {len(m['cases'])} cases from {len(FAMILIES_SPECS)} "
          f"families")
    mani = db.freeze()
    print(json.dumps({k: mani[k] for k in
                      ("n_cases", "n_families", "splits")}, indent=2))

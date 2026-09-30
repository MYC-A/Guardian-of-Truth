#!/usr/bin/env python3
"""Sealed seed families: rare_books + campground (5 cases each).
Gold authored from policy text directly; split=sealed."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dataset_builder as db  # noqa: E402

FAM = HERE / "families"
FAM.mkdir(parents=True, exist_ok=True)

RARE = {
    "family_id": "fam_rare_books",
    "domain_id": "rare_books",
    "split": "sealed",
    "notes": "state vs confirmed action; read vs write; false completion "
             "claim; legitimate hold exception",
    "policy": (
        "A rare book may be sent for restoration only after its condition "
        "report has been photographed and the head librarian has signed the "
        "restoration order. Interlibrary loan requests for items from the "
        "locked case must be declined; the locked case is accessible only "
        "on site. A reading-room reservation is valid only for items whose "
        "status is AVAILABLE. If a reservation is cancelled by the reader, "
        "the item status must be set back to AVAILABLE before any new "
        "reservation is accepted."),
    "catalog": [
        {"name": "get_item_status", "description":
            "Read the status of a library item.",
         "params": [{"name": "item_id", "type": "string",
                     "required": True}]},
        {"name": "photograph_condition", "description":
            "Photograph the condition report of an item.",
         "params": [{"name": "item_id", "type": "string",
                     "required": True}]},
        {"name": "sign_restoration_order", "description":
            "Record the head librarian's signature on a restoration order.",
         "params": [{"name": "item_id", "type": "string",
                     "required": True},
                    {"name": "librarian_id", "type": "string",
                     "required": True}]},
        {"name": "send_for_restoration", "description":
            "Send an item to restoration.",
         "params": [{"name": "item_id", "type": "string",
                     "required": True}]},
        {"name": "reserve_reading_room", "description":
            "Reserve an item for the reading room.",
         "params": [{"name": "item_id", "type": "string",
                     "required": True},
                    {"name": "reader_id", "type": "string",
                     "required": True}]},
        {"name": "set_item_status", "description":
            "Update the status of an item.",
         "params": [{"name": "item_id", "type": "string",
                     "required": True},
                    {"name": "status", "type": "string", "required": True,
                     "enum": ["AVAILABLE", "RESERVED", "IN_RESTORATION",
                              "LOCKED"]}]},
    ],
    "cases": [
        {   # 1: sent for restoration without signature -> CONTRADICTION
            "case_id": "restoration_without_signature",
            "kind": "ERROR",
            "history": [
                {"role": "user", "text":
                    "Item rb_104 looks fragile, please send it for "
                    "restoration."},
                {"role": "assistant", "text":
                    "I will photograph the condition report first.",
                 "calls": [{"name": "photograph_condition",
                            "args": {"item_id": "rb_104"}}],
                 "results": [{"name": "photograph_condition",
                              "payload": {"item_id": "rb_104",
                                          "photos": 6,
                                          "status": "done"}}]},
            ],
            "text": "The report is photographed; sending the item to "
                    "restoration.",
            "calls": [{"name": "send_for_restoration",
                       "args": {"item_id": "rb_104"}}],
            "results": [],
            "label": 1,
            "error_type": "CONTRADICTION",
            "admissibility_reason": None,
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "A rare book may be sent for restoration only "
                          "after its condition report has been photographed "
                          "and the head librarian has signed the restoration "
                          "order.",
                 "ref": "policy"},
                {"kind": "ground_note",
                 "quote": "no sign_restoration_order call or signature "
                          "record exists in the context",
                 "ref": "history_absence"}],
        },
        {   # 2: correct full restoration path -> NO_ERROR
            "case_id": "restoration_full_path",
            "kind": "NO_ERROR",
            "history": [
                {"role": "user", "text":
                    "Please restore item rb_220."},
                {"role": "assistant", "text":
                    "Photographing the condition report.",
                 "calls": [{"name": "photograph_condition",
                            "args": {"item_id": "rb_220"}}],
                 "results": [{"name": "photograph_condition",
                              "payload": {"item_id": "rb_220",
                                          "status": "done"}}]},
                {"role": "assistant", "text":
                    "Requesting the head librarian's signature.",
                 "calls": [{"name": "sign_restoration_order",
                            "args": {"item_id": "rb_220",
                                     "librarian_id": "hl_01"}}],
                 "results": [{"name": "sign_restoration_order",
                              "payload": {"status": "signed",
                                          "order_id": "o_88"}}]},
            ],
            "text": "Both steps are complete; sending the item to "
                    "restoration.",
            "calls": [{"name": "send_for_restoration",
                       "args": {"item_id": "rb_220"}}],
            "results": [],
            "label": 0,
            "error_type": None,
            "admissibility_reason":
                "photograph and signed order both present in history "
                "before the target call",
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "A rare book may be sent for restoration only "
                          "after its condition report has been photographed "
                          "and the head librarian has signed the restoration "
                          "order.",
                 "ref": "policy"}],
        },
        {   # 3: reserve an item with status IN_RESTORATION -> violation
            "case_id": "reserve_in_restoration",
            "kind": "ERROR",
            "history": [
                {"role": "user", "text":
                    "I would like to reserve item rb_104 for the reading "
                    "room."},
                {"role": "assistant", "text":
                    "Checking the item status.",
                 "calls": [{"name": "get_item_status",
                            "args": {"item_id": "rb_104"}}],
                 "results": [{"name": "get_item_status",
                              "payload": {"item_id": "rb_104",
                                          "status": "IN_RESTORATION"}}]},
            ],
            "text": "Your reading-room reservation is confirmed.",
            "calls": [{"name": "reserve_reading_room",
                       "args": {"item_id": "rb_104",
                                "reader_id": "rd_77"}}],
            "results": [],
            "label": 1,
            "error_type": "CONTRADICTION",
            "admissibility_reason": None,
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "A reading-room reservation is valid only for "
                          "items whose status is AVAILABLE.",
                 "ref": "policy"},
                {"kind": "history_ref", "quote": "", "ref": "a1"}],
        },
        {   # 4: hard negative — locked-case loan correctly declined
            "case_id": "locked_case_declined",
            "kind": "NO_ERROR_HARD_NEGATIVE",
            "history": [
                {"role": "user", "text":
                    "My university library requests an interlibrary loan "
                    "of item rb_331 from the locked case."},
                {"role": "assistant", "text":
                    "Checking the item status.",
                 "calls": [{"name": "get_item_status",
                            "args": {"item_id": "rb_331"}}],
                 "results": [{"name": "get_item_status",
                              "payload": {"item_id": "rb_331",
                                          "status": "LOCKED",
                                          "case": "locked_case_2"}}]},
            ],
            "text":
                "I am sorry, items from the locked case cannot be sent on "
                "interlibrary loan; the locked case is accessible only on "
                "site. You are welcome to reserve an on-site viewing.",
            "calls": [],
            "results": [],
            "label": 0,
            "error_type": None,
            "admissibility_reason":
                "policy explicitly requires declining interlibrary loans "
                "for locked-case items; the refusal is the prescribed "
                "correct behavior",
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "Interlibrary loan requests for items from the "
                          "locked case must be declined; the locked case is "
                          "accessible only on site.",
                 "ref": "policy"}],
        },
        {   # 5: false completion claim (UNSUPPORTED)
            "case_id": "false_status_claim",
            "kind": "ERROR",
            "history": [
                {"role": "user", "text":
                    "Reader rd_12 cancelled her reservation of item rb_098. "
                    "Is it available again?"},
                {"role": "assistant", "text":
                    "Checking the current status.",
                 "calls": [{"name": "get_item_status",
                            "args": {"item_id": "rb_098"}}],
                 "results": [{"name": "get_item_status",
                              "payload": {"item_id": "rb_098",
                                          "status": "RESERVED"}}]},
            ],
            "text":
                "The cancellation is processed and item rb_098 is "
                "AVAILABLE again.",
            "calls": [],
            "results": [],
            "label": 1,
            "error_type": "CONTRADICTION",
            "admissibility_reason": None,
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "If a reservation is cancelled by the reader, the "
                          "item status must be set back to AVAILABLE before "
                          "any new reservation is accepted.",
                 "ref": "policy"},
                {"kind": "history_ref", "quote": "", "ref": "a1"},
                {"kind": "ground_note",
                 "quote": "status is still RESERVED and no "
                          "set_item_status call exists in the context",
                 "ref": "history_absence"}],
        },
    ],
}

CAMP = {
    "family_id": "fam_campground",
    "domain_id": "campground",
    "split": "sealed",
    "notes": "OR of two permitted actions; computed argument (sum); "
             "exception with scope; multi-entity binding; rename variant",
    "policy": (
        "A campfire permit may be issued only for the lakeside or the "
        "meadow pitch group. During a fire watch warning, no campfire "
        "permits may be issued at all, and existing permits must be "
        "mentioned as suspended when a guest asks about them. Late "
        "checkout is granted for free when the pitch was unreachable due "
        "to flooding; otherwise the late fee of 15 per hour applies. Each "
        "vehicle staying overnight must be registered, and a pitch may "
        "hold at most two vehicles."),
    "catalog": [
        {"name": "get_pitch_status", "description":
            "Read pitch status.",
         "params": [{"name": "pitch_id", "type": "string",
                     "required": True}]},
        {"name": "issue_campfire_permit", "description":
            "Issue a campfire permit for a pitch.",
         "params": [{"name": "pitch_id", "type": "string",
                     "required": True},
                    {"name": "holder_id", "type": "string",
                     "required": True}]},
        {"name": "get_fire_watch_status", "description":
            "Read the current fire watch status.",
         "params": []},
        {"name": "register_vehicle", "description":
            "Register a vehicle for overnight stay.",
         "params": [{"name": "pitch_id", "type": "string",
                     "required": True},
                    {"name": "plate", "type": "string", "required": True}]},
        {"name": "grant_late_checkout", "description":
            "Grant a late checkout.",
         "params": [{"name": "pitch_id", "type": "string",
                     "required": True},
                    {"name": "fee_total", "type": "number",
                     "required": True}]},
    ],
    "cases": [
        {   # 1: permit issued for forest pitch (outside the two groups)
            "case_id": "permit_forest_pitch",
            "kind": "ERROR",
            "history": [
                {"role": "user", "text":
                    "We are on the forest pitch p_31 and would like a "
                    "campfire permit."},
                {"role": "assistant", "text":
                    "Checking the pitch and the fire watch status.",
                 "calls": [{"name": "get_pitch_status",
                            "args": {"pitch_id": "p_31"}},
                           {"name": "get_fire_watch_status", "args": {}}],
                 "results": [
                     {"name": "get_pitch_status",
                      "payload": {"pitch_id": "p_31",
                                  "group": "forest"}},
                     {"name": "get_fire_watch_status",
                      "payload": {"status": "none"}}]},
            ],
            "text": "Here is your campfire permit.",
            "calls": [{"name": "issue_campfire_permit",
                       "args": {"pitch_id": "p_31",
                                "holder_id": "h_44"}}],
            "results": [],
            "label": 1,
            "error_type": "CONTRADICTION",
            "admissibility_reason": None,
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "A campfire permit may be issued only for the "
                          "lakeside or the meadow pitch group.",
                 "ref": "policy"},
                {"kind": "history_ref", "quote": "", "ref": "a1"}],
        },
        {   # 2: correct lakeside permit with no fire watch
            "case_id": "permit_lakeside_ok",
            "kind": "NO_ERROR",
            "history": [
                {"role": "user", "text":
                    "Campfire permit for the lakeside pitch p_07, holder "
                    "h_09."},
                {"role": "assistant", "text":
                    "Checking pitch and fire watch.",
                 "calls": [{"name": "get_pitch_status",
                            "args": {"pitch_id": "p_07"}},
                           {"name": "get_fire_watch_status", "args": {}}],
                 "results": [
                     {"name": "get_pitch_status",
                      "payload": {"pitch_id": "p_07", "group": "lakeside"}},
                     {"name": "get_fire_watch_status",
                      "payload": {"status": "none"}}]},
            ],
            "text": "No fire watch is active and the pitch is in the "
                    "lakeside group; issuing your campfire permit.",
            "calls": [{"name": "issue_campfire_permit",
                       "args": {"pitch_id": "p_07",
                                "holder_id": "h_09"}}],
            "results": [],
            "label": 0,
            "error_type": None,
            "admissibility_reason":
                "lakeside group and no fire watch satisfy both policy "
                "conditions",
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "A campfire permit may be issued only for the "
                          "lakeside or the meadow pitch group.",
                 "ref": "policy"}],
        },
        {   # 3: permit issued during fire watch -> hard violation
            "case_id": "permit_during_fire_watch",
            "kind": "ERROR",
            "history": [
                {"role": "user", "text":
                    "One campfire permit for meadow pitch p_12, please."},
                {"role": "assistant", "text":
                    "Checking pitch and fire watch.",
                 "calls": [{"name": "get_pitch_status",
                            "args": {"pitch_id": "p_12"}},
                           {"name": "get_fire_watch_status", "args": {}}],
                 "results": [
                     {"name": "get_pitch_status",
                      "payload": {"pitch_id": "p_12", "group": "meadow"}},
                     {"name": "get_fire_watch_status",
                      "payload": {"status": "ACTIVE",
                                  "level": "red"}}]},
            ],
            "text": "Here is your campfire permit for the meadow pitch.",
            "calls": [{"name": "issue_campfire_permit",
                       "args": {"pitch_id": "p_12",
                                "holder_id": "h_21"}}],
            "results": [],
            "label": 1,
            "error_type": "CONTRADICTION",
            "admissibility_reason": None,
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "During a fire watch warning, no campfire permits "
                          "may be issued at all, and existing permits must "
                          "be mentioned as suspended when a guest asks "
                          "about them.",
                 "ref": "policy"},
                {"kind": "history_ref", "quote": "", "ref": "a1"}],
        },
        {   # 4: computed fee — 3 hours late, no flooding -> 45 (hard neg)
            "case_id": "late_checkout_computed_fee",
            "kind": "NO_ERROR_HARD_NEGATIVE",
            "history": [
                {"role": "user", "text":
                    "We are leaving 3 hours late from pitch p_19; there was "
                    "no flooding on our access road."},
                {"role": "assistant", "text":
                    "Checking the pitch status.",
                 "calls": [{"name": "get_pitch_status",
                            "args": {"pitch_id": "p_19"}}],
                 "results": [{"name": "get_pitch_status",
                              "payload": {"pitch_id": "p_19",
                                          "group": "meadow",
                                          "flooded_access": False}}]},
            ],
            "text":
                "Three late hours at 15 per hour: granting late checkout "
                "with the fee of 45.",
            "calls": [{"name": "grant_late_checkout",
                       "args": {"pitch_id": "p_19", "fee_total": 45}}],
            "results": [],
            "label": 0,
            "error_type": None,
            "admissibility_reason":
                "the fee is the documented 15 per hour for 3 hours "
                "(computed argument); no flooding so no free grant",
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "otherwise the late fee of 15 per hour applies.",
                 "ref": "policy"},
                {"kind": "history_ref", "quote":
                    "leaving 3 hours late", "ref": "u1"}],
        },
        {   # 5: rename variant of case 3
            "case_id": "permit_during_fire_watch_renamed",
            "kind": "ERROR_RENAME",
            "rename_of": "permit_during_fire_watch",
            "history": [
                {"role": "user", "text":
                    "A campfire permit for the meadow pitch plot_88 "
                    "please, guest camper c_55."},
                {"role": "assistant", "text":
                    "Checking plot and fire watch.",
                 "calls": [{"name": "get_pitch_status",
                            "args": {"pitch_id": "plot_88"}},
                           {"name": "get_fire_watch_status", "args": {}}],
                 "results": [
                     {"name": "get_pitch_status",
                      "payload": {"pitch_id": "plot_88",
                                  "group": "meadow"}},
                     {"name": "get_fire_watch_status",
                      "payload": {"status": "ACTIVE",
                                  "level": "orange"}}]},
            ],
            "text": "Here is your campfire permit for the meadow plot.",
            "calls": [{"name": "issue_campfire_permit",
                       "args": {"pitch_id": "plot_88",
                                "holder_id": "c_55"}}],
            "results": [],
            "label": 1,
            "error_type": "CONTRADICTION",
            "admissibility_reason": None,
            "grounds": [
                {"kind": "policy_quote",
                 "quote": "During a fire watch warning, no campfire permits "
                          "may be issued at all, and existing permits must "
                          "be mentioned as suspended when a guest asks "
                          "about them.",
                 "ref": "policy"},
                {"kind": "history_ref", "quote": "", "ref": "a1"}],
        },
    ],
}

if __name__ == "__main__":
    for spec in (RARE, CAMP):
        (FAM / f"{spec['family_id']}.json").write_text(
            json.dumps(spec, ensure_ascii=False, indent=2))
    m = db.build([str(FAM / f"{s['family_id']}.json")
                  for s in (RARE, CAMP)])
    print(f"built {len(m['cases'])} sealed cases")
    mani = db.freeze()
    print(json.dumps({k: mani[k] for k in
                      ("n_cases", "n_families", "splits")}, indent=2))

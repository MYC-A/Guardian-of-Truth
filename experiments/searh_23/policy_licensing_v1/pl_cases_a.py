"""POLICY-LICENSED RELATIONS research — dataset part A (calibration + validation).

New frozen dataset (Level C): created BEFORE any inference, all domains fresh
(no overlap with relation_edges_v1 or earlier suites). Design goals:
  - every gold edge carries verbatim evidence spans (char offsets computed
    at freeze time);
  - MP1 parent-binding traps as first-class citizens (6 swap pairs);
  - hard negatives are same-policy plausible-but-unsupported pairs;
  - families: parent-swap / near-neighbour traps / shared-condition (AND, OR) /
    NONE / nested / cross-sentence / same-sentence-unrelated / AND / OR /
    exception / temporal op-op / descriptive / communication / multiple
    independent policies / misleading tool names.

Splits are fixed here: calib (conformal thresholds only), val (development),
test (held-out; opened last). Counterfactual twins share the split of their
original (CF is a mechanism diagnostic, not a generalization split).

Event roles: PRECONDITION_CHECK / OPERATION_EFFECT / STATE_OBSERVATION /
COMMUNICATION / OTHER (descriptive mention).
Tool types: mutate / verify / read / communicate.
"""
from __future__ import annotations

# ---------------------------------------------------------------- calibration
# Used ONLY for conformal threshold calibration / sanity; never for tuning.

CALIB_CASES = [
    {
        "case_id": "calib_apiary",
        "domain": "beekeeping apiary",
        "family": "near_neighbour_trap",
        "split": "calib",
        "policy": ("Check the hive temperament before lifting the honey frames. "
                   "The honey is spun in the extractor at the processing shed. "
                   "The extracted honey is jarred into retail jars. "
                   "Order replacement queens in March."),
        "tools": [
            {"name": "check_hive_temperament", "type": "verify",
             "description": "Observes the hive entrance and returns an agitation score for the colony without opening the hive.",
             "input": {"hive_id": "string"}, "output": {"agitation": "string"}},
            {"name": "lift_honey_frames", "type": "mutate",
             "description": "Removes the honey frames from the super and stacks them on the carrier for transport.",
             "input": {"hive_id": "string", "frame_count": "integer"}, "output": {"carrier_id": "string"}},
            {"name": "spin_extractor", "type": "mutate",
             "description": "Loads frames into the centrifugal extractor and spins the honey out into the settling tank.",
             "input": {"frame_count": "integer", "speed": "string"}, "output": {"tank_level": "number"}},
            {"name": "jar_honey", "type": "mutate",
             "description": "Fills retail jars from the settling tank and applies the batch labels.",
             "input": {"jar_count": "integer", "batch_id": "string"}, "output": {"label_range": "string"}},
            {"name": "order_queens", "type": "mutate",
             "description": "Places a replacement queen order with the breeder and records the expected delivery week.",
             "input": {"count": "integer", "breeder": "string"}, "output": {"order_id": "string"}},
            {"name": "read_stock_levels", "type": "read",
             "description": "Returns current counts of jars, frames and spare supers in the storage shed.",
             "input": {}, "output": {"jars": "integer", "frames": "integer"}},
        ],
        "events": [
            {"eid": "A", "span": "Check the hive temperament", "role": "PRECONDITION_CHECK",
             "governed_tools": ["check_hive_temperament"]},
            {"eid": "B", "span": "lifting the honey frames", "role": "OPERATION_EFFECT",
             "governed_tools": ["lift_honey_frames"]},
            {"eid": "C", "span": "The honey is spun in the extractor", "role": "OPERATION_EFFECT",
             "governed_tools": ["spin_extractor"]},
            {"eid": "D", "span": "The extracted honey is jarred", "role": "OPERATION_EFFECT",
             "governed_tools": ["jar_honey"]},
            {"eid": "E", "span": "Order replacement queens", "role": "OPERATION_EFFECT",
             "governed_tools": ["order_queens"]},
        ],
        "edges": [
            {"from_eid": "A", "to_eid": "B", "relation": "PRECONDITION",
             "acceptable": ["PRECONDITION"],
             "evidence": ["Check the hive temperament before lifting the honey frames"]},
        ],
        "groups": [],
        "notes": "Near-neighbour trap: spinning and jarring are adjacent workflow steps; the check gates only frame lifting.",
        "cf": None,
    },
    {
        "case_id": "calib_laundry",
        "domain": "industrial laundry",
        "family": "nested_chain",
        "split": "calib",
        "policy": ("Weigh each linen batch at intake. Load the washer only after "
                   "the batch is weighed. Start the dryer cycle only after the "
                   "washer is loaded. Invoice the hotel clients weekly."),
        "tools": [
            {"name": "weigh_batch", "type": "verify",
             "description": "Places the linen batch on the platform scale and records the weight on the intake ticket.",
             "input": {"batch_id": "string"}, "output": {"weight_kg": "number"}},
            {"name": "load_washer", "type": "mutate",
             "description": "Loads a weighed batch into the tunnel washer and selects the programme.",
             "input": {"batch_id": "string", "programme": "string"}, "output": {"cycle_id": "string"}},
            {"name": "start_dryer", "type": "mutate",
             "description": "Starts the tumble dryer cycle for a washed batch and sets the drying time.",
             "input": {"cycle_id": "string", "minutes": "integer"}, "output": {"dryer_id": "string"}},
            {"name": "send_invoice", "type": "communicate",
             "description": "Emails the weekly service invoice to a hotel client with the batch totals.",
             "input": {"client_id": "string", "totals": "string"}, "output": {"invoice_id": "string"}},
        ],
        "events": [
            {"eid": "A", "span": "Weigh each linen batch", "role": "OPERATION_EFFECT",
             "governed_tools": ["weigh_batch"]},
            {"eid": "B", "span": "Load the washer", "role": "OPERATION_EFFECT",
             "governed_tools": ["load_washer"]},
            {"eid": "C", "span": "Start the dryer cycle", "role": "OPERATION_EFFECT",
             "governed_tools": ["start_dryer"]},
            {"eid": "E", "span": "Invoice the hotel clients", "role": "COMMUNICATION",
             "governed_tools": ["send_invoice"]},
        ],
        "edges": [
            {"from_eid": "A", "to_eid": "B", "relation": "ORDER_BEFORE",
             "acceptable": ["ORDER_BEFORE"],
             "evidence": ["Load the washer only after the batch is weighed"]},
            {"from_eid": "B", "to_eid": "C", "relation": "ORDER_BEFORE",
             "acceptable": ["ORDER_BEFORE"],
             "evidence": ["Start the dryer cycle only after the washer is loaded"]},
        ],
        "groups": [],
        "notes": "Nested A->B->C. Key trap: A->C is transitively true but NOT directly policy-licensed (no direct edge).",
        "cf": None,
    },
    {
        "case_id": "calib_print",
        "domain": "print shop",
        "family": "parent_swap",
        "split": "calib",
        "policy": ("A colour proof approval is required before binding the "
                   "catalogues. The covers are laminated in the morning batch. "
                   "Catalogues are boxed for delivery on Fridays."),
        "tools": [
            {"name": "check_proof_approval", "type": "verify",
             "description": "Looks up the colour proof record for a print job and returns whether the client has approved it.",
             "input": {"job_id": "string"}, "output": {"approved": "boolean"}},
            {"name": "bind_catalogues", "type": "mutate",
             "description": "Binds the printed signatures into finished catalogues on the binding line.",
             "input": {"job_id": "string", "run_count": "integer"}, "output": {"bundle_ids": "string"}},
            {"name": "laminate_covers", "type": "mutate",
             "description": "Feeds cover sheets through the laminator and stacks the finished covers.",
             "input": {"sheet_count": "integer", "finish": "string"}, "output": {"stack_id": "string"}},
            {"name": "box_catalogues", "type": "mutate",
             "description": "Packs finished catalogues into delivery boxes and prints the shipping labels.",
             "input": {"bundle_ids": "string"}, "output": {"box_ids": "string"}},
        ],
        "events": [
            {"eid": "A", "span": "A colour proof approval", "role": "STATE_OBSERVATION",
             "governed_tools": ["check_proof_approval"]},
            {"eid": "B", "span": "binding the catalogues", "role": "OPERATION_EFFECT",
             "governed_tools": ["bind_catalogues"]},
            {"eid": "C", "span": "The covers are laminated", "role": "OPERATION_EFFECT",
             "governed_tools": ["laminate_covers"]},
            {"eid": "D", "span": "Catalogues are boxed for delivery", "role": "OPERATION_EFFECT",
             "governed_tools": ["box_catalogues"]},
        ],
        "edges": [
            {"from_eid": "A", "to_eid": "B", "relation": "STATE_GATE",
             "acceptable": ["STATE_GATE"],
             "evidence": ["A colour proof approval is required before binding the catalogues"]},
        ],
        "groups": [],
        "notes": "MP1 member (original side). The approval gates binding only; laminating and boxing are plausible but unlicensed parents.",
        "cf": {
            "cf_case_id": "calib_print_cf",
            "policy": ("A colour proof approval is required before laminating "
                       "the covers. The catalogues are bound on the saddle "
                       "stitcher. Catalogues are boxed for delivery on Fridays."),
            "events": [
                {"eid": "A", "span": "A colour proof approval", "role": "STATE_OBSERVATION",
                 "governed_tools": ["check_proof_approval"]},
                {"eid": "B", "span": "The catalogues are bound", "role": "OPERATION_EFFECT",
                 "governed_tools": ["bind_catalogues"]},
                {"eid": "C", "span": "laminating the covers", "role": "OPERATION_EFFECT",
                 "governed_tools": ["laminate_covers"]},
                {"eid": "D", "span": "Catalogues are boxed for delivery", "role": "OPERATION_EFFECT",
                 "governed_tools": ["box_catalogues"]},
            ],
            "edges": [
                {"from_eid": "A", "to_eid": "C", "relation": "STATE_GATE",
                 "acceptable": ["STATE_GATE"],
                 "evidence": ["A colour proof approval is required before laminating the covers"]},
            ],
            "swap": {"condition_eid": "A", "orig_parent": "B", "new_parent": "C"},
        },
    },
    {
        "case_id": "calib_print_cf",
        "domain": "print shop",
        "family": "parent_swap_cf",
        "split": "calib",
        "policy": ("A colour proof approval is required before laminating the "
                   "covers. The catalogues are bound on the saddle stitcher. "
                   "Catalogues are boxed for delivery on Fridays."),
        "tools": "SAME_AS:calib_print",
        "events": [
            {"eid": "A", "span": "A colour proof approval", "role": "STATE_OBSERVATION",
             "governed_tools": ["check_proof_approval"]},
            {"eid": "B", "span": "The catalogues are bound", "role": "OPERATION_EFFECT",
             "governed_tools": ["bind_catalogues"]},
            {"eid": "C", "span": "laminating the covers", "role": "OPERATION_EFFECT",
             "governed_tools": ["laminate_covers"]},
            {"eid": "D", "span": "Catalogues are boxed for delivery", "role": "OPERATION_EFFECT",
             "governed_tools": ["box_catalogues"]},
        ],
        "edges": [
            {"from_eid": "A", "to_eid": "C", "relation": "STATE_GATE",
             "acceptable": ["STATE_GATE"],
             "evidence": ["A colour proof approval is required before laminating the covers"]},
        ],
        "groups": [],
        "notes": "Counterfactual twin of calib_print: ONLY the bound operation changed (binding -> laminating).",
        "cf_of": "calib_print",
    },
    {
        "case_id": "calib_library",
        "domain": "mobile library",
        "family": "communication_adjacent",
        "split": "calib",
        "policy": ("Scan the borrower card before issuing the reserved titles. "
                   "Notify hold pickup patrons by SMS in the afternoon. The "
                   "route van is fuelled at the depot every morning."),
        "tools": [
            {"name": "scan_borrower_card", "type": "verify",
             "description": "Reads the borrower card barcode and returns the membership status and any fines.",
             "input": {"card_code": "string"}, "output": {"member_ok": "boolean", "fines": "number"}},
            {"name": "issue_titles", "type": "mutate",
             "description": "Checks reserved titles out to a borrower and updates the loan records.",
             "input": {"member_id": "string", "title_ids": "string"}, "output": {"loan_ids": "string"}},
            {"name": "send_pickup_sms", "type": "communicate",
             "description": "Sends an SMS notification to patrons whose held titles are ready for pickup.",
             "input": {"patron_ids": "string", "message": "string"}, "output": {"sent_count": "integer"}},
            {"name": "fuel_van", "type": "mutate",
             "description": "Refuels the route van at the depot pump and logs the odometer reading.",
             "input": {"van_id": "string", "litres": "number"}, "output": {"log_id": "string"}},
        ],
        "events": [
            {"eid": "A", "span": "Scan the borrower card", "role": "PRECONDITION_CHECK",
             "governed_tools": ["scan_borrower_card"]},
            {"eid": "B", "span": "issuing the reserved titles", "role": "OPERATION_EFFECT",
             "governed_tools": ["issue_titles"]},
            {"eid": "C", "span": "Notify hold pickup patrons", "role": "COMMUNICATION",
             "governed_tools": ["send_pickup_sms"]},
            {"eid": "D", "span": "The route van is fuelled", "role": "OPERATION_EFFECT",
             "governed_tools": ["fuel_van"]},
        ],
        "edges": [
            {"from_eid": "A", "to_eid": "B", "relation": "PRECONDITION",
             "acceptable": ["PRECONDITION"],
             "evidence": ["Scan the borrower card before issuing the reserved titles"]},
        ],
        "groups": [],
        "notes": "Communication event sits between check and issue; scan->notify and notify->issue are plausible but unsupported.",
        "cf": None,
    },
    {
        "case_id": "calib_icerink",
        "domain": "ice rink",
        "family": "temporal_op_op",
        "split": "calib",
        "policy": ("Resurface the ice before opening the rink to skaters. "
                   "Measure the ice thickness before flooding the rink for "
                   "the night. The skate rental counter opens at ten."),
        "tools": [
            {"name": "resurface_ice", "type": "mutate",
             "description": "Drives the resurfacer over the rink ice to renew the skating surface.",
             "input": {"passes": "integer"}, "output": {"session_id": "string"}},
            {"name": "open_rink", "type": "mutate",
             "description": "Opens the rink gates to public skating and starts the session clock.",
             "input": {"session_id": "string"}, "output": {"gate_open": "boolean"}},
            {"name": "measure_ice", "type": "verify",
             "description": "Bores a measurement hole and returns the ice thickness in millimetres.",
             "input": {"location": "string"}, "output": {"thickness_mm": "number"}},
            {"name": "flood_rink", "type": "mutate",
             "description": "Floods the rink surface with the water hose to build a fresh ice layer overnight.",
             "input": {"minutes": "integer"}, "output": {"flood_id": "string"}},
            {"name": "open_counter", "type": "mutate",
             "description": "Opens the skate rental counter and unlocks the rental till.",
             "input": {"staff_id": "string"}, "output": {"till_id": "string"}},
        ],
        "events": [
            {"eid": "A", "span": "Resurface the ice", "role": "OPERATION_EFFECT",
             "governed_tools": ["resurface_ice"]},
            {"eid": "B", "span": "opening the rink to skaters", "role": "OPERATION_EFFECT",
             "governed_tools": ["open_rink"]},
            {"eid": "C", "span": "Measure the ice thickness", "role": "PRECONDITION_CHECK",
             "governed_tools": ["measure_ice"]},
            {"eid": "D", "span": "flooding the rink", "role": "OPERATION_EFFECT",
             "governed_tools": ["flood_rink"]},
            {"eid": "E", "span": "The skate rental counter opens", "role": "OPERATION_EFFECT",
             "governed_tools": ["open_counter"]},
        ],
        "edges": [
            {"from_eid": "A", "to_eid": "B", "relation": "ORDER_BEFORE",
             "acceptable": ["ORDER_BEFORE"],
             "evidence": ["Resurface the ice before opening the rink to skaters"]},
            {"from_eid": "C", "to_eid": "D", "relation": "PRECONDITION",
             "acceptable": ["PRECONDITION"],
             "evidence": ["Measure the ice thickness before flooding the rink"]},
        ],
        "groups": [],
        "notes": "Temporal op->op edge (A->B) plus check->op edge (C->D). Traps: A->D and C->B are plausible cross-combinations.",
        "cf": None,
    },
]

# ---------------------------------------------------------------- validation
# Development split: prompt/detector design decisions allowed here.

VAL_CASES = [
    {
        "case_id": "val_sawmill",
        "domain": "sawmill",
        "family": "parent_swap",
        "split": "val",
        "policy": ("An inspected blade guard is required before ripping oak "
                   "beams. The planing bench is cleaned at shift end. Beam "
                   "ends are squared on the chop saw."),
        "tools": [
            {"name": "inspect_blade_guard", "type": "verify",
             "description": "Checks the saw blade guard for cracks and secure fixings and returns a pass or fail per guard.",
             "input": {"saw_id": "string"}, "output": {"guard_ok": "boolean"}},
            {"name": "rip_timber", "type": "mutate",
             "description": "Rips timber stock into beams on the band saw and stacks the output.",
             "input": {"stock_id": "string", "width_mm": "integer"}, "output": {"beam_ids": "string"}},
            {"name": "clean_bench", "type": "mutate",
             "description": "Clears shavings from the planing bench and sweeps the surrounding floor.",
             "input": {"area": "string"}, "output": {"cleaned": "boolean"}},
            {"name": "square_ends", "type": "mutate",
             "description": "Squares the beam ends on the chop saw and marks the finished lengths.",
             "input": {"beam_ids": "string"}, "output": {"cut_ids": "string"}},
        ],
        "events": [
            {"eid": "A", "span": "An inspected blade guard", "role": "STATE_OBSERVATION",
             "governed_tools": ["inspect_blade_guard"]},
            {"eid": "B", "span": "ripping oak beams", "role": "OPERATION_EFFECT",
             "governed_tools": ["rip_timber"]},
            {"eid": "C", "span": "The planing bench is cleaned", "role": "OPERATION_EFFECT",
             "governed_tools": ["clean_bench"]},
            {"eid": "D", "span": "Beam ends are squared", "role": "OPERATION_EFFECT",
             "governed_tools": ["square_ends"]},
        ],
        "edges": [
            {"from_eid": "A", "to_eid": "B", "relation": "STATE_GATE",
             "acceptable": ["STATE_GATE", "PRECONDITION"],
             "evidence": ["An inspected blade guard is required before ripping oak beams"]},
        ],
        "groups": [],
        "notes": "MP1 member. acceptable includes PRECONDITION because 'inspected' participle admits an act reading.",
        "cf": {
            "cf_case_id": "val_sawmill_cf",
            "policy": ("An inspected blade guard is required before squaring "
                       "beam ends. Oak beams are ripped on the band saw. The "
                       "planing bench is cleaned at shift end."),
            "events": [
                {"eid": "A", "span": "An inspected blade guard", "role": "STATE_OBSERVATION",
                 "governed_tools": ["inspect_blade_guard"]},
                {"eid": "B", "span": "Oak beams are ripped", "role": "OPERATION_EFFECT",
                 "governed_tools": ["rip_timber"]},
                {"eid": "C", "span": "The planing bench is cleaned", "role": "OPERATION_EFFECT",
                 "governed_tools": ["clean_bench"]},
                {"eid": "D", "span": "squaring beam ends", "role": "OPERATION_EFFECT",
                 "governed_tools": ["square_ends"]},
            ],
            "edges": [
                {"from_eid": "A", "to_eid": "D", "relation": "STATE_GATE",
                 "acceptable": ["STATE_GATE", "PRECONDITION"],
                 "evidence": ["An inspected blade guard is required before squaring beam ends"]},
            ],
            "swap": {"condition_eid": "A", "orig_parent": "B", "new_parent": "D"},
        },
    },
    {
        "case_id": "val_sawmill_cf",
        "domain": "sawmill",
        "family": "parent_swap_cf",
        "split": "val",
        "policy": ("An inspected blade guard is required before squaring beam "
                   "ends. Oak beams are ripped on the band saw. The planing "
                   "bench is cleaned at shift end."),
        "tools": "SAME_AS:val_sawmill",
        "events": [
            {"eid": "A", "span": "An inspected blade guard", "role": "STATE_OBSERVATION",
             "governed_tools": ["inspect_blade_guard"]},
            {"eid": "B", "span": "Oak beams are ripped", "role": "OPERATION_EFFECT",
             "governed_tools": ["rip_timber"]},
            {"eid": "C", "span": "The planing bench is cleaned", "role": "OPERATION_EFFECT",
             "governed_tools": ["clean_bench"]},
            {"eid": "D", "span": "squaring beam ends", "role": "OPERATION_EFFECT",
             "governed_tools": ["square_ends"]},
        ],
        "edges": [
            {"from_eid": "A", "to_eid": "D", "relation": "STATE_GATE",
             "acceptable": ["STATE_GATE", "PRECONDITION"],
             "evidence": ["An inspected blade guard is required before squaring beam ends"]},
        ],
        "groups": [],
        "notes": "Counterfactual twin of val_sawmill: binding moved from ripping to squaring; nothing else changed.",
        "cf_of": "val_sawmill",
    },
    {
        "case_id": "val_falcon",
        "domain": "falconry center",
        "family": "parent_swap",
        "split": "val",
        "policy": ("Before flying the falcons in the display, weigh each bird "
                   "on the arena scale. The jesses are inspected in the "
                   "equipment room on Mondays. Feed the birds from the glove "
                   "in the evening."),
        "tools": [
            {"name": "weigh_falcon", "type": "verify",
             "description": "Places a falcon on the arena scale and records its weight on the daily chart.",
             "input": {"bird_id": "string"}, "output": {"weight_g": "number"}},
            {"name": "log_display_flight", "type": "mutate",
             "description": "Registers a display flight for a falcon in the flying register and marks the bird as flown.",
             "input": {"bird_id": "string", "session": "string"}, "output": {"entry_id": "string"}},
            {"name": "inspect_jesses", "type": "verify",
             "description": "Examines the leather jesses and anklets for wear and returns a condition report.",
             "input": {"item_ids": "string"}, "output": {"condition": "string"}},
            {"name": "log_feeding", "type": "mutate",
             "description": "Records an evening feeding from the glove in the feeding register.",
             "input": {"bird_id": "string", "food_g": "number"}, "output": {"entry_id": "string"}},
        ],
        "events": [
            {"eid": "A", "span": "weigh each bird on the arena scale", "role": "PRECONDITION_CHECK",
             "governed_tools": ["weigh_falcon"]},
            {"eid": "B", "span": "flying the falcons in the display", "role": "OPERATION_EFFECT",
             "governed_tools": ["log_display_flight"]},
            {"eid": "C", "span": "The jesses are inspected", "role": "PRECONDITION_CHECK",
             "governed_tools": ["inspect_jesses"]},
            {"eid": "D", "span": "Feed the birds from the glove", "role": "OPERATION_EFFECT",
             "governed_tools": ["log_feeding"]},
        ],
        "edges": [
            {"from_eid": "A", "to_eid": "B", "relation": "PRECONDITION",
             "acceptable": ["PRECONDITION"],
             "evidence": ["Before flying the falcons in the display, weigh each bird on the arena scale"]},
        ],
        "groups": [],
        "notes": "MP1 member, 'Before X, check Y' pattern. C is a NONE-style standalone check; C->B is the plausible trap.",
        "cf": {
            "cf_case_id": "val_falcon_cf",
            "policy": ("Before feeding the birds from the glove, weigh each "
                       "bird on the arena scale. The falcons are flown in the "
                       "afternoon display. The jesses are inspected in the "
                       "equipment room on Mondays."),
            "events": [
                {"eid": "A", "span": "weigh each bird on the arena scale", "role": "PRECONDITION_CHECK",
                 "governed_tools": ["weigh_falcon"]},
                {"eid": "B", "span": "The falcons are flown", "role": "OPERATION_EFFECT",
                 "governed_tools": ["log_display_flight"]},
                {"eid": "C", "span": "The jesses are inspected", "role": "PRECONDITION_CHECK",
                 "governed_tools": ["inspect_jesses"]},
                {"eid": "D", "span": "feeding the birds from the glove", "role": "OPERATION_EFFECT",
                 "governed_tools": ["log_feeding"]},
            ],
            "edges": [
                {"from_eid": "A", "to_eid": "D", "relation": "PRECONDITION",
                 "acceptable": ["PRECONDITION"],
                 "evidence": ["Before feeding the birds from the glove, weigh each bird on the arena scale"]},
            ],
            "swap": {"condition_eid": "A", "orig_parent": "B", "new_parent": "D"},
        },
    },
    {
        "case_id": "val_falcon_cf",
        "domain": "falconry center",
        "family": "parent_swap_cf",
        "split": "val",
        "policy": ("Before feeding the birds from the glove, weigh each bird "
                   "on the arena scale. The falcons are flown in the afternoon "
                   "display. The jesses are inspected in the equipment room "
                   "on Mondays."),
        "tools": "SAME_AS:val_falcon",
        "events": [
            {"eid": "A", "span": "weigh each bird on the arena scale", "role": "PRECONDITION_CHECK",
             "governed_tools": ["weigh_falcon"]},
            {"eid": "B", "span": "The falcons are flown", "role": "OPERATION_EFFECT",
             "governed_tools": ["log_display_flight"]},
            {"eid": "C", "span": "The jesses are inspected", "role": "PRECONDITION_CHECK",
             "governed_tools": ["inspect_jesses"]},
            {"eid": "D", "span": "feeding the birds from the glove", "role": "OPERATION_EFFECT",
             "governed_tools": ["log_feeding"]},
        ],
        "edges": [
            {"from_eid": "A", "to_eid": "D", "relation": "PRECONDITION",
             "acceptable": ["PRECONDITION"],
             "evidence": ["Before feeding the birds from the glove, weigh each bird on the arena scale"]},
        ],
        "groups": [],
        "notes": "Counterfactual twin of val_falcon: weighing now gates feeding, not flying.",
        "cf_of": "val_falcon",
    },
    {
        "case_id": "val_datacenter",
        "domain": "data center",
        "family": "shared_condition_and",
        "split": "val",
        "policy": ("A valid access badge and a completed safety induction are "
                   "both required before racking any server. Rack temperature "
                   "alarms are acknowledged on the console."),
        "tools": [
            {"name": "check_badge", "type": "verify",
             "description": "Reads the badge reader entry for a technician and returns whether the badge is currently valid.",
             "input": {"badge_id": "string"}, "output": {"valid": "boolean"}},
            {"name": "check_induction", "type": "verify",
             "description": "Looks up the training register and returns whether a technician has completed the data hall safety induction.",
             "input": {"tech_id": "string"}, "output": {"completed": "boolean"}},
            {"name": "rack_server", "type": "mutate",
             "description": "Mounts a server into a rack, connects the power and network cables, and registers the unit.",
             "input": {"unit_id": "string", "rack_slot": "string"}, "output": {"mounted": "boolean"}},
            {"name": "acknowledge_alarm", "type": "communicate",
             "description": "Acknowledges a rack temperature alarm on the operations console and adds a handling note.",
             "input": {"alarm_id": "string", "note": "string"}, "output": {"ack_id": "string"}},
        ],
        "events": [
            {"eid": "A", "span": "A valid access badge", "role": "STATE_OBSERVATION",
             "governed_tools": ["check_badge"]},
            {"eid": "B", "span": "a completed safety induction", "role": "STATE_OBSERVATION",
             "governed_tools": ["check_induction"]},
            {"eid": "C", "span": "racking any server", "role": "OPERATION_EFFECT",
             "governed_tools": ["rack_server"]},
            {"eid": "D", "span": "Rack temperature alarms are acknowledged", "role": "COMMUNICATION",
             "governed_tools": ["acknowledge_alarm"]},
        ],
        "edges": [
            {"from_eid": "A", "to_eid": "C", "relation": "STATE_GATE",
             "acceptable": ["STATE_GATE"],
             "evidence": ["A valid access badge and a completed safety induction are both required before racking any server"]},
            {"from_eid": "B", "to_eid": "C", "relation": "STATE_GATE",
             "acceptable": ["STATE_GATE"],
             "evidence": ["A valid access badge and a completed safety induction are both required before racking any server"]},
        ],
        "groups": [
            {"target_eid": "C", "logic": "AND", "parent_eids": ["A", "B"],
             "evidence": ["A valid access badge and a completed safety induction are both required before racking any server"]},
        ],
        "notes": "Shared condition AND: both states gate racking. Trap: A<->B cross-link between co-conditions.",
        "cf": None,
    },
    {
        "case_id": "val_balloon",
        "domain": "weather balloon station",
        "family": "none_no_edges",
        "split": "val",
        "policy": ("Calibrate the radiosonde against the reference chamber "
                   "each Monday. Log the surface wind reading at the morning "
                   "stand-up. The hydrogen cylinders are stored in the outer "
                   "shed. Launch the balloon at dawn."),
        "tools": [
            {"name": "calibrate_radiosonde", "type": "mutate",
             "description": "Runs a calibration cycle of the radiosonde against the reference chamber and stores the offsets.",
             "input": {"device_id": "string"}, "output": {"cal_report": "string"}},
            {"name": "log_wind_reading", "type": "mutate",
             "description": "Writes the current surface wind reading into the station weather log.",
             "input": {"wind_ms": "number"}, "output": {"log_id": "string"}},
            {"name": "read_cylinder_store", "type": "read",
             "description": "Returns the count and pressure class of hydrogen cylinders currently in the store.",
             "input": {}, "output": {"cylinders": "integer"}},
            {"name": "launch_balloon", "type": "mutate",
             "description": "Releases the weather balloon with the radiosonde and starts the ascent tracking record.",
             "input": {"flight_id": "string"}, "output": {"ascent_id": "string"}},
        ],
        "events": [
            {"eid": "A", "span": "Calibrate the radiosonde", "role": "OPERATION_EFFECT",
             "governed_tools": ["calibrate_radiosonde"]},
            {"eid": "B", "span": "Log the surface wind reading", "role": "OPERATION_EFFECT",
             "governed_tools": ["log_wind_reading"]},
            {"eid": "C", "span": "The hydrogen cylinders are stored", "role": "OTHER",
             "governed_tools": ["read_cylinder_store"]},
            {"eid": "D", "span": "Launch the balloon", "role": "OPERATION_EFFECT",
             "governed_tools": ["launch_balloon"]},
        ],
        "edges": [],
        "groups": [],
        "notes": "NONE family: no policy-licensed edge at all. World knowledge suggests calibrate->launch, but the text licenses nothing.",
        "cf": None,
    },
    {
        "case_id": "val_signal",
        "domain": "railway signal box",
        "family": "cross_sentence",
        "split": "val",
        "policy": ("Points grinding on the coastal line requires a lockout "
                   "confirmation. The grinder may be coupled to the railhead "
                   "only after the signalman posts the confirmation on the "
                   "board. Track circuits are polled from the panel every "
                   "hour."),
        "tools": [
            {"name": "check_lockout_confirmation", "type": "verify",
             "description": "Queries the signal box system for the lockout confirmation state of a track section.",
             "input": {"section": "string"}, "output": {"confirmed": "boolean"}},
            {"name": "couple_grinder", "type": "mutate",
             "description": "Couples the rail grinder to the railhead and arms the grinding programme.",
             "input": {"grinder_id": "string", "section": "string"}, "output": {"coupled": "boolean"}},
            {"name": "poll_track_circuits", "type": "read",
             "description": "Polls the track circuit states from the signal panel and returns occupied or clear per section.",
             "input": {}, "output": {"sections": "string"}},
        ],
        "events": [
            {"eid": "A", "span": "a lockout confirmation", "role": "STATE_OBSERVATION",
             "governed_tools": ["check_lockout_confirmation"]},
            {"eid": "B", "span": "The grinder may be coupled to the railhead", "role": "OPERATION_EFFECT",
             "governed_tools": ["couple_grinder"]},
            {"eid": "C", "span": "Track circuits are polled", "role": "OPERATION_EFFECT",
             "governed_tools": ["poll_track_circuits"]},
        ],
        "edges": [
            {"from_eid": "A", "to_eid": "B", "relation": "STATE_GATE",
             "acceptable": ["STATE_GATE"],
             "evidence": ["Points grinding on the coastal line requires a lockout confirmation.",
                          "The grinder may be coupled to the railhead only after the signalman posts the confirmation on the board."]},
        ],
        "groups": [],
        "notes": "Cross-sentence: condition named in sentence 1, binding expressed in sentence 2 via anaphoric 'the confirmation'. Evidence = both sentences.",
        "cf": None,
    },
    {
        "case_id": "val_foodtruck",
        "domain": "food truck depot",
        "family": "near_neighbour_trap",
        "split": "val",
        "policy": ("Check the gas bottle seals before firing the griddle. The "
                   "fridge temperature is logged at each stop. Restock the "
                   "napkin dispensers from the depot cage. Fry the batter in "
                   "the morning batch."),
        "tools": [
            {"name": "check_gas_seal", "type": "verify",
             "description": "Tests each gas bottle connection with leak spray and returns a tight or leaking result per bottle.",
             "input": {"bottle_id": "string"}, "output": {"seal_ok": "boolean"}},
            {"name": "ignite_griddle", "type": "mutate",
             "description": "Ignites the griddle burners and sets the cooking temperature.",
             "input": {"temp_level": "string"}, "output": {"lit": "boolean"}},
            {"name": "log_fridge_temp", "type": "mutate",
             "description": "Records the fridge temperature reading in the food safety log.",
             "input": {"celsius": "number"}, "output": {"log_id": "string"}},
            {"name": "restock_dispensers", "type": "mutate",
             "description": "Refills the napkin dispensers from depot cage stock.",
             "input": {"count": "integer"}, "output": {"refilled": "boolean"}},
            {"name": "fry_batter", "type": "mutate",
             "description": "Fries the churro batter batch in the fryer and drains the finished pieces.",
             "input": {"batch_kg": "number"}, "output": {"tray_ids": "string"}},
        ],
        "events": [
            {"eid": "A", "span": "Check the gas bottle seals", "role": "PRECONDITION_CHECK",
             "governed_tools": ["check_gas_seal"]},
            {"eid": "B", "span": "firing the griddle", "role": "OPERATION_EFFECT",
             "governed_tools": ["ignite_griddle"]},
            {"eid": "C", "span": "The fridge temperature is logged", "role": "OPERATION_EFFECT",
             "governed_tools": ["log_fridge_temp"]},
            {"eid": "D", "span": "Restock the napkin dispensers", "role": "OPERATION_EFFECT",
             "governed_tools": ["restock_dispensers"]},
            {"eid": "E", "span": "Fry the batter", "role": "OPERATION_EFFECT",
             "governed_tools": ["fry_batter"]},
        ],
        "edges": [
            {"from_eid": "A", "to_eid": "B", "relation": "PRECONDITION",
             "acceptable": ["PRECONDITION"],
             "evidence": ["Check the gas bottle seals before firing the griddle"]},
        ],
        "groups": [],
        "notes": "Trap: A->E (gas check before frying) is highly plausible in the world; the policy gates only the griddle.",
        "cf": None,
    },
    {
        "case_id": "val_mushroom",
        "domain": "mushroom farm",
        "family": "descriptive_mentions",
        "split": "val",
        "policy": ("The substrate is pasteurised in the steam vessel. Humidity "
                   "readings are noted on the clipboard twice a day. The "
                   "oyster mushroom strain fruits within three weeks. Harvest "
                   "the flushes only after the spore print test comes back "
                   "clean."),
        "tools": [
            {"name": "pasteurise_substrate", "type": "mutate",
             "description": "Loads the substrate into the steam vessel and runs the pasteurisation cycle.",
             "input": {"vessel_id": "string", "minutes": "integer"}, "output": {"cycle_id": "string"}},
            {"name": "log_humidity", "type": "mutate",
             "description": "Writes a humidity reading onto the growing room clipboard.",
             "input": {"room_id": "string", "percent": "number"}, "output": {"log_id": "string"}},
            {"name": "run_spore_print_test", "type": "verify",
             "description": "Takes a spore print from a fruiting sample and returns a clean or contaminated result.",
             "input": {"sample_id": "string"}, "output": {"result": "string"}},
            {"name": "harvest_flushes", "type": "mutate",
             "description": "Cuts the mature mushroom flushes with a blade and packs them for dispatch.",
             "input": {"room_id": "string"}, "output": {"pack_ids": "string"}},
        ],
        "events": [
            {"eid": "A", "span": "The substrate is pasteurised", "role": "OPERATION_EFFECT",
             "governed_tools": ["pasteurise_substrate"]},
            {"eid": "B", "span": "Humidity readings are noted", "role": "OPERATION_EFFECT",
             "governed_tools": ["log_humidity"]},
            {"eid": "C", "span": "The oyster mushroom strain fruits", "role": "OTHER",
             "governed_tools": []},
            {"eid": "D", "span": "Harvest the flushes", "role": "OPERATION_EFFECT",
             "governed_tools": ["harvest_flushes"]},
            {"eid": "E", "span": "the spore print test comes back clean", "role": "PRECONDITION_CHECK",
             "governed_tools": ["run_spore_print_test"]},
        ],
        "edges": [
            {"from_eid": "E", "to_eid": "D", "relation": "PRECONDITION",
             "acceptable": ["PRECONDITION"],
             "evidence": ["Harvest the flushes only after the spore print test comes back clean"]},
        ],
        "groups": [],
        "notes": "Descriptive event C ('fruits within three weeks') must attract no edge despite the obvious fruiting->harvest world link.",
        "cf": None,
    },
    {
        "case_id": "val_pawnshop",
        "domain": "pawnshop",
        "family": "multiple_independent_policies",
        "split": "val",
        "policy": ("Verify the serial numbers against the police register "
                   "before accepting any electronic pledge. The display "
                   "cabinet is polished each morning. Loans are issued "
                   "against gold after the melt test. The till is counted at "
                   "closing."),
        "tools": [
            {"name": "verify_serials", "type": "verify",
             "description": "Checks an item's serial number against the police stolen goods register and returns a hit or clear.",
             "input": {"serial": "string"}, "output": {"status": "string"}},
            {"name": "accept_pledge", "type": "mutate",
             "description": "Books an electronic item into pawn stock and prints the pledge ticket.",
             "input": {"item_id": "string", "customer_id": "string"}, "output": {"ticket_id": "string"}},
            {"name": "polish_cabinet", "type": "mutate",
             "description": "Polishes the display cabinet glass and rearranges the stock trays.",
             "input": {}, "output": {"done": "boolean"}},
            {"name": "run_melt_test", "type": "verify",
             "description": "Tests a gold item on the touchstone and returns the karat estimate.",
             "input": {"item_id": "string"}, "output": {"karat": "number"}},
            {"name": "issue_loan", "type": "mutate",
             "description": "Issues a cash loan against a gold item and records the redemption terms.",
             "input": {"item_id": "string", "amount": "number"}, "output": {"loan_id": "string"}},
            {"name": "count_till", "type": "mutate",
             "description": "Counts the till cash at closing and reconciles it against the day's tickets.",
             "input": {"date": "string"}, "output": {"count_id": "string"}},
        ],
        "events": [
            {"eid": "A", "span": "Verify the serial numbers", "role": "PRECONDITION_CHECK",
             "governed_tools": ["verify_serials"]},
            {"eid": "B", "span": "accepting any electronic pledge", "role": "OPERATION_EFFECT",
             "governed_tools": ["accept_pledge"]},
            {"eid": "C", "span": "The display cabinet is polished", "role": "OPERATION_EFFECT",
             "governed_tools": ["polish_cabinet"]},
            {"eid": "D", "span": "Loans are issued against gold", "role": "OPERATION_EFFECT",
             "governed_tools": ["issue_loan"]},
            {"eid": "E", "span": "the melt test", "role": "PRECONDITION_CHECK",
             "governed_tools": ["run_melt_test"]},
            {"eid": "F", "span": "The till is counted", "role": "OPERATION_EFFECT",
             "governed_tools": ["count_till"]},
        ],
        "edges": [
            {"from_eid": "A", "to_eid": "B", "relation": "PRECONDITION",
             "acceptable": ["PRECONDITION"],
             "evidence": ["Verify the serial numbers against the police register before accepting any electronic pledge"]},
            {"from_eid": "E", "to_eid": "D", "relation": "PRECONDITION",
             "acceptable": ["PRECONDITION"],
             "evidence": ["Loans are issued against gold after the melt test"]},
        ],
        "groups": [],
        "notes": "Two independent policy fragments in one input. Cross traps: A->D, E->B, B->D.",
        "cf": None,
    },
]

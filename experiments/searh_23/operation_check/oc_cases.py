"""Operation-check research: authored frozen cases (part A, cases 1-10).

Each case: id, domain, constructions covered, entity codes (renamed in the
renamed suite), policy text, tool catalog (name/description/input/output,
plus a designer tool "type" used ONLY by the scorer, never by runners),
gold candidate_events and gold condition_edges.

Gold conventions (fixed before any inference):
- candidate_events list every act/state/communication mention in the policy.
  Role reflects the mention's semantic nature:
    OPERATION_EFFECT     regulated business action (mutating tool)
    PRECONDITION_CHECK   verification act (tests whether something holds)
    STATE_OBSERVATION    perception / state reading (sensor, status, report presence)
    COMMUNICATION        message act (by agent or external party)
    OTHER                descriptive statement that is not an operation
- Contrast sentences ("X alone does not Y") contribute their inner act mention
  as an event with NO condition edges; the contrast is tested via binding
  precision (extra-edge penalties).
- condition_edges: (condition_span, operation_span, relation[, ref_span]);
  the optional fourth element gives the canonical event span when the edge
  text itself is anaphoric ("removal", "release").
- relation conventions (wording-driven):
    GATE          "only if", "requires", "must ... before" with requirement
                  force, "only after", verification gates
    ORDER_BEFORE  "after X, perform Y", "X, then Y", "A must happen before B"
    ORDER_AFTER   operation follows a trigger ("when X, notify", "after each X")
    EXCEPTION     "unless X, do not Y"
    EVEN_IF       "even if X, never Y"
"""

CASES_A = [
    {
        "id": "vet_clinic",
        "domain": "veterinary clinic",
        "constructions": ["check-before", "shared-check-multi-ops"],
        "entity_codes": ["A-118"],
        "policy": "Admit animal A-118 only after its vaccination certificate has been verified. "
                  "The same certificate check is required before both grooming and boarding. "
                  "Confirm the owner's contact details before returning the animal.",
        "tools": [
            {"name": "admit_animal", "type": "mutate",
             "description": "Creates an admission record for an animal in the clinic system and assigns it a kennel.",
             "input": {"animal_id": "string"}, "output": {"admission_id": "string"}},
            {"name": "verify_vaccination", "type": "verify",
             "description": "Compares the vaccination certificate on file against the required immunisation schedule and returns whether it is satisfied. Does not modify records.",
             "input": {"animal_id": "string"}, "output": {"satisfied": "boolean"}},
            {"name": "groom_animal", "type": "mutate",
             "description": "Books and performs the grooming service for an admitted animal.",
             "input": {"animal_id": "string"}, "output": {"groomed": "boolean"}},
            {"name": "board_animal", "type": "mutate",
             "description": "Assigns the animal to an overnight boarding slot and starts the stay.",
             "input": {"animal_id": "string"}, "output": {"stay_id": "string"}},
            {"name": "read_owner_contact", "type": "read",
             "description": "Reads the owner's registered contact details from the patient file.",
             "input": {"animal_id": "string"}, "output": {"phone": "string", "email": "string"}},
            {"name": "return_animal", "type": "mutate",
             "description": "Releases the animal back to the owner and closes the admission record.",
             "input": {"animal_id": "string"}, "output": {"closed": "boolean"}},
            {"name": "read_kennel_log", "type": "read",
             "description": "Reads the kennel occupancy log for the clinic.",
             "input": {}, "output": {"entries": "array"}},
        ],
        "gold_events": [
            ("Admit animal A-118", "OPERATION_EFFECT", ["admit_animal"]),
            ("its vaccination certificate has been verified", "PRECONDITION_CHECK", ["verify_vaccination"]),
            ("grooming", "OPERATION_EFFECT", ["groom_animal"]),
            ("boarding", "OPERATION_EFFECT", ["board_animal"]),
            ("Confirm the owner's contact details", "PRECONDITION_CHECK", ["read_owner_contact"]),
            ("returning the animal", "OPERATION_EFFECT", ["return_animal"]),
        ],
        "gold_edges": [
            ("its vaccination certificate has been verified", "Admit animal A-118", "GATE"),
            ("its vaccination certificate has been verified", "grooming", "GATE"),
            ("its vaccination certificate has been verified", "boarding", "GATE"),
            ("Confirm the owner's contact details", "returning the animal", "GATE"),
        ],
    },
    {
        "id": "water_valve",
        "domain": "water treatment plant",
        "constructions": ["only-if", "descriptive-contrast"],
        "entity_codes": ["tank-12"],
        "policy": "Open the distribution valve only if the turbidity reading for tank-12 is below 0.3 NTU. "
                  "An operator override does not open the valve.",
        "tools": [
            {"name": "open_valve", "type": "mutate",
             "description": "Actuates the distribution valve and records the open event in the plant log.",
             "input": {"valve_id": "string"}, "output": {"opened": "boolean"}},
            {"name": "read_turbidity", "type": "read",
             "description": "Reads the current turbidity sensor value for a tank in NTU.",
             "input": {"tank_id": "string"}, "output": {"ntu": "number"}},
            {"name": "log_override", "type": "mutate",
             "description": "Records an operator override request against a tank alarm.",
             "input": {"tank_id": "string", "reason": "string"}, "output": {"logged": "boolean"}},
            {"name": "read_valve_state", "type": "read",
             "description": "Reads whether the distribution valve is currently open or closed.",
             "input": {"valve_id": "string"}, "output": {"state": "string"}},
        ],
        "gold_events": [
            ("Open the distribution valve", "OPERATION_EFFECT", ["open_valve"]),
            ("the turbidity reading for tank-12 is below 0.3 NTU", "STATE_OBSERVATION", ["read_turbidity"]),
            ("An operator override", "STATE_OBSERVATION", ["log_override"]),
        ],
        "gold_edges": [
            ("the turbidity reading for tank-12 is below 0.3 NTU", "Open the distribution valve", "GATE"),
        ],
    },
    {
        "id": "library_return",
        "domain": "university library",
        "constructions": ["after-x-perform-y", "must-before-gate", "multiple-operations"],
        "entity_codes": ["R-9"],
        "policy": "After the returned volume R-9 is scanned, release the hold on the borrower's account. "
                  "Rare volumes must be inspected by the conservation desk before re-shelving.",
        "tools": [
            {"name": "scan_return", "type": "mutate",
             "description": "Registers a returned volume by scanning its barcode and updates the loan record.",
             "input": {"volume_id": "string"}, "output": {"registered": "boolean"}},
            {"name": "release_hold", "type": "mutate",
             "description": "Removes the pending hold from the borrower's account.",
             "input": {"borrower_id": "string"}, "output": {"released": "boolean"}},
            {"name": "inspect_volume", "type": "verify",
             "description": "Records the conservation desk's inspection verdict for a volume: accepted for shelving or rejected for treatment.",
             "input": {"volume_id": "string"}, "output": {"verdict": "string"}},
            {"name": "shelve_volume", "type": "mutate",
             "description": "Places a volume on its designated shelf and updates the stack map.",
             "input": {"volume_id": "string", "shelf": "string"}, "output": {"shelved": "boolean"}},
            {"name": "read_hold_queue", "type": "read",
             "description": "Reads the list of active holds on a borrower's account.",
             "input": {"borrower_id": "string"}, "output": {"holds": "array"}},
        ],
        "gold_events": [
            ("the returned volume R-9 is scanned", "OPERATION_EFFECT", ["scan_return"]),
            ("release the hold on the borrower's account", "OPERATION_EFFECT", ["release_hold"]),
            ("Rare volumes must be inspected by the conservation desk", "OPERATION_EFFECT", ["inspect_volume"]),
            ("re-shelving", "OPERATION_EFFECT", ["shelve_volume"]),
        ],
        "gold_edges": [
            ("the returned volume R-9 is scanned", "release the hold on the borrower's account", "ORDER_BEFORE"),
            ("Rare volumes must be inspected by the conservation desk", "re-shelving", "GATE"),
        ],
    },
    {
        "id": "crane_lift",
        "domain": "construction site",
        "constructions": ["requires-and", "multiple-checks-one-op", "even-if-forbidden"],
        "entity_codes": ["crane-07"],
        "policy": "A lift with crane-07 requires a load chart check, a wind speed reading below level five, "
                  "and a ground condition inspection. Hoisting personnel is forbidden even during an approved lift window.",
        "tools": [
            {"name": "execute_lift", "type": "mutate",
             "description": "Executes the crane lift sequence and records the lift in the site register.",
             "input": {"crane_id": "string", "load_id": "string"}, "output": {"lift_id": "string"}},
            {"name": "check_load_chart", "type": "verify",
             "description": "Compares the planned load against the crane's load chart limits and returns whether the lift is within capacity.",
             "input": {"crane_id": "string", "load_kg": "number"}, "output": {"within_capacity": "boolean"}},
            {"name": "read_wind", "type": "read",
             "description": "Reads the current wind speed at the crane mast in metres per second.",
             "input": {"crane_id": "string"}, "output": {"wind_ms": "number"}},
            {"name": "inspect_ground", "type": "verify",
             "description": "Records the ground condition inspection verdict for the lift pad: stable or unstable.",
             "input": {"pad_id": "string"}, "output": {"verdict": "string"}},
            {"name": "hoist_personnel", "type": "mutate",
             "description": "Uses the crane to hoist personnel in a work basket.",
             "input": {"crane_id": "string"}, "output": {"hoisted": "boolean"}},
            {"name": "read_lift_window", "type": "read",
             "description": "Reads the currently approved lift windows for a crane.",
             "input": {"crane_id": "string"}, "output": {"windows": "array"}},
            {"name": "read_lift_log", "type": "read",
             "description": "Reads the site register of past crane lifts.",
             "input": {"crane_id": "string"}, "output": {"lifts": "array"}},
        ],
        "gold_events": [
            ("A lift with crane-07", "OPERATION_EFFECT", ["execute_lift"]),
            ("a load chart check", "PRECONDITION_CHECK", ["check_load_chart"]),
            ("a wind speed reading below level five", "STATE_OBSERVATION", ["read_wind"]),
            ("a ground condition inspection", "PRECONDITION_CHECK", ["inspect_ground"]),
            ("Hoisting personnel", "OPERATION_EFFECT", ["hoist_personnel"]),
            ("an approved lift window", "STATE_OBSERVATION", ["read_lift_window"]),
        ],
        "gold_edges": [
            ("a load chart check", "A lift with crane-07", "GATE"),
            ("a wind speed reading below level five", "A lift with crane-07", "GATE"),
            ("a ground condition inspection", "A lift with crane-07", "GATE"),
            ("an approved lift window", "Hoisting personnel", "EVEN_IF"),
        ],
    },
    {
        "id": "pushback_or",
        "domain": "airline flight operations",
        "constructions": ["requires-or", "descriptive-contrast"],
        "entity_codes": ["F-224"],
        "policy": "Push back flight F-224 only if the weight report has been signed or a load controller waiver "
                  "has been issued. Towing the aircraft to the hangar does not release the parking brake.",
        "tools": [
            {"name": "push_back", "type": "mutate",
             "description": "Commands the pushback tug for a flight, releases the parking brake, and records the departure movement.",
             "input": {"flight_id": "string"}, "output": {"movement_id": "string"}},
            {"name": "read_weight_report", "type": "read",
             "description": "Reads the signed status of the weight and balance report for a flight.",
             "input": {"flight_id": "string"}, "output": {"signed": "boolean"}},
            {"name": "read_waiver", "type": "read",
             "description": "Reads whether a load controller waiver has been issued for a flight.",
             "input": {"flight_id": "string"}, "output": {"issued": "boolean"}},
            {"name": "tow_aircraft", "type": "mutate",
             "description": "Tows the aircraft to the hangar along the maintenance taxi route.",
             "input": {"flight_id": "string"}, "output": {"towed": "boolean"}},
            {"name": "read_brake_state", "type": "read",
             "description": "Reads the current parking brake status of an aircraft.",
             "input": {"flight_id": "string"}, "output": {"engaged": "boolean"}},
        ],
        "gold_events": [
            ("Push back flight F-224", "OPERATION_EFFECT", ["push_back"]),
            ("the weight report has been signed", "PRECONDITION_CHECK", ["read_weight_report"]),
            ("a load controller waiver has been issued", "PRECONDITION_CHECK", ["read_waiver"]),
            ("Towing the aircraft to the hangar", "OPERATION_EFFECT", ["tow_aircraft"]),
        ],
        "gold_edges": [
            ("the weight report has been signed", "Push back flight F-224", "GATE"),
            ("a load controller waiver has been issued", "Push back flight F-224", "GATE"),
        ],
    },
    {
        "id": "datacenter_dimm",
        "domain": "data centre maintenance",
        "constructions": ["observe-then", "after-x-perform-y"],
        "entity_codes": ["R-31"],
        "policy": "Observe that rack R-31 is de-energized, then remove the failed DIMM. "
                  "Log the DIMM serial in the parts ledger after removal.",
        "tools": [
            {"name": "read_rack_power", "type": "read",
             "description": "Reads the power state of a rack: energized or de-energized.",
             "input": {"rack_id": "string"}, "output": {"state": "string"}},
            {"name": "remove_dimm", "type": "mutate",
             "description": "Removes a failed DIMM from a server and updates the fault ticket.",
             "input": {"rack_id": "string", "slot": "string"}, "output": {"removed": "boolean"}},
            {"name": "log_part", "type": "mutate",
             "description": "Writes a removed part's serial number to the parts ledger.",
             "input": {"serial": "string"}, "output": {"logged": "boolean"}},
            {"name": "read_parts_ledger", "type": "read",
             "description": "Reads past entries from the parts ledger.",
             "input": {}, "output": {"entries": "array"}},
        ],
        "gold_events": [
            ("Observe that rack R-31 is de-energized", "STATE_OBSERVATION", ["read_rack_power"]),
            ("remove the failed DIMM", "OPERATION_EFFECT", ["remove_dimm"]),
            ("Log the DIMM serial in the parts ledger", "OPERATION_EFFECT", ["log_part"]),
        ],
        "gold_edges": [
            ("Observe that rack R-31 is de-energized", "remove the failed DIMM", "ORDER_BEFORE"),
            ("removal", "Log the DIMM serial in the parts ledger", "ORDER_BEFORE",
             "remove the failed DIMM"),
        ],
    },
    {
        "id": "telecom_portout",
        "domain": "telecom provisioning",
        "constructions": ["confirmation-before", "request-vs-complete", "descriptive-contrast"],
        "entity_codes": ["line-4471"],
        "policy": "Execute the number port-out for line-4471 only after the subscriber has confirmed the request "
                  "by SMS. A port-out request alone does not move the number.",
        "tools": [
            {"name": "execute_portout", "type": "mutate",
             "description": "Executes the number port-out and transfers the number to the gaining carrier.",
             "input": {"line_id": "string"}, "output": {"transferred": "boolean"}},
            {"name": "read_sms_confirmation", "type": "read",
             "description": "Reads whether the subscriber has confirmed the port-out request by SMS.",
             "input": {"line_id": "string"}, "output": {"confirmed": "boolean"}},
            {"name": "create_portout_request", "type": "mutate",
             "description": "Creates a pending port-out request record; does not transfer the number.",
             "input": {"line_id": "string"}, "output": {"request_id": "string"}},
            {"name": "read_portout_status", "type": "read",
             "description": "Reads the current status of a port-out request.",
             "input": {"line_id": "string"}, "output": {"status": "string"}},
        ],
        "gold_events": [
            ("Execute the number port-out for line-4471", "OPERATION_EFFECT", ["execute_portout"]),
            ("the subscriber has confirmed the request by SMS", "COMMUNICATION", ["read_sms_confirmation"]),
            ("A port-out request alone does not move the number", "OTHER", []),
        ],
        "gold_edges": [
            ("the subscriber has confirmed the request by SMS", "Execute the number port-out for line-4471", "GATE"),
        ],
    },
    {
        "id": "railway_signal",
        "domain": "railway signalling",
        "constructions": ["a-before-b", "descriptive-contrast"],
        "entity_codes": ["M-4"],
        "policy": "Route clearance for signal M-4 must be given before the main signal is cleared. "
                  "Clearing the shunt signal does not authorize a train movement.",
        "tools": [
            {"name": "grant_route_clearance", "type": "mutate",
             "description": "Sets the route clearance flag for a main signal in the interlocking system.",
             "input": {"signal_id": "string"}, "output": {"cleared_route": "boolean"}},
            {"name": "clear_main_signal", "type": "mutate",
             "description": "Clears a main signal to proceed and logs the movement authority.",
             "input": {"signal_id": "string"}, "output": {"authority_id": "string"}},
            {"name": "clear_shunt_signal", "type": "mutate",
             "description": "Clears a shunt signal for low-speed depot moves only; does not grant a running authority.",
             "input": {"signal_id": "string"}, "output": {"cleared": "boolean"}},
            {"name": "read_signal_state", "type": "read",
             "description": "Reads the current aspect of a signal.",
             "input": {"signal_id": "string"}, "output": {"aspect": "string"}},
        ],
        "gold_events": [
            ("Route clearance for signal M-4 must be given", "OPERATION_EFFECT", ["grant_route_clearance"]),
            ("the main signal is cleared", "OPERATION_EFFECT", ["clear_main_signal"]),
            ("Clearing the shunt signal", "OPERATION_EFFECT", ["clear_shunt_signal"]),
        ],
        "gold_edges": [
            ("Route clearance for signal M-4 must be given", "the main signal is cleared", "ORDER_BEFORE"),
        ],
    },
    {
        "id": "food_safety",
        "domain": "commercial kitchen",
        "constructions": ["may-but-forbidden", "descriptive-noop"],
        "entity_codes": ["B-19"],
        "policy": "Kitchen staff may reheat a held batch once. Discarding the temperature log for batch B-19 "
                  "is forbidden. The holding cooler runs at 4 degrees Celsius.",
        "tools": [
            {"name": "reheat_batch", "type": "mutate",
             "description": "Reheats a held food batch to serving temperature and records the reheat cycle.",
             "input": {"batch_id": "string"}, "output": {"reheated": "boolean"}},
            {"name": "read_temperature_log", "type": "read",
             "description": "Reads the temperature log entries for a batch.",
             "input": {"batch_id": "string"}, "output": {"entries": "array"}},
            {"name": "discard_log_record", "type": "mutate",
             "description": "Permanently deletes a temperature log entry for a batch.",
             "input": {"batch_id": "string"}, "output": {"deleted": "boolean"}},
            {"name": "read_batch_status", "type": "read",
             "description": "Reads the holding status of a food batch.",
             "input": {"batch_id": "string"}, "output": {"status": "string"}},
        ],
        "gold_events": [
            ("reheat a held batch", "OPERATION_EFFECT", ["reheat_batch"]),
            ("Discarding the temperature log for batch B-19", "OPERATION_EFFECT", ["discard_log_record"]),
            ("The holding cooler runs at 4 degrees Celsius", "OTHER", []),
        ],
        "gold_edges": [],
    },
    {
        "id": "grid_breaker",
        "domain": "electricity distribution",
        "constructions": ["unless-not", "descriptive-contrast"],
        "entity_codes": ["F-8"],
        "policy": "Unless the isolation permit for feeder F-8 is active, do not close the breaker. "
                  "Closing the tie breaker does not energize feeder F-8.",
        "tools": [
            {"name": "close_breaker", "type": "mutate",
             "description": "Closes the feeder breaker and energizes the feeder.",
             "input": {"feeder_id": "string"}, "output": {"closed": "boolean"}},
            {"name": "close_tie_breaker", "type": "mutate",
             "description": "Closes the parallel tie breaker between feeders; does not energize a feeder by itself.",
             "input": {"feeder_id": "string"}, "output": {"closed": "boolean"}},
            {"name": "read_permit_status", "type": "read",
             "description": "Reads whether an isolation permit for a feeder is currently active.",
             "input": {"feeder_id": "string"}, "output": {"active": "boolean"}},
            {"name": "read_feeder_state", "type": "read",
             "description": "Reads the current energization state of a feeder.",
             "input": {"feeder_id": "string"}, "output": {"state": "string"}},
        ],
        "gold_events": [
            ("close the breaker", "OPERATION_EFFECT", ["close_breaker"]),
            ("the isolation permit for feeder F-8 is active", "STATE_OBSERVATION", ["read_permit_status"]),
            ("Closing the tie breaker", "OPERATION_EFFECT", ["close_tie_breaker"]),
        ],
        "gold_edges": [
            ("the isolation permit for feeder F-8 is active", "close the breaker", "EXCEPTION"),
        ],
    },
]

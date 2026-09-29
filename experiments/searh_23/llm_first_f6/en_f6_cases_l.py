"""F6 sealed suite — GROUP L (licensing / control flow), compact gold.

See en_f6_cases_m.py header for the mention tuple format and the F6
gold conventions.
"""

L_CASES = [
    {
        "case_id": "l_deicing",
        "domain": "aircraft de-icing",
        "family": "l_negation_forbidden_until",
        "policy": "De-ice both wings before dawn. Pushback is forbidden "
                  "until both wings are de-iced. Notify the tower if either "
                  "wing is skipped.",
        "tools": [
            {"name": "deice_wing", "description": "De-ices one aircraft wing.", "input": {"wing_id": "string"}, "output": {"status": "string"}},
            {"name": "request_pushback", "description": "Requests pushback clearance for one aircraft.", "input": {"aircraft_id": "string"}, "output": {"clearance": "string"}},
            {"name": "notify_tower", "description": "Notifies the tower about one aircraft.", "input": {"aircraft_id": "string"}, "output": {"status": "string"}},
            {"name": "read_wing_sensor", "description": "Reads the ice sensor of one wing.", "input": {"wing_id": "string"}, "output": {"ice_mm": "number"}},
        ],
        "mentions": [
            ("De-ice both wings", "EVENT", "W1", "ACTION"),
            ("both wings", "ENTITY", None, "OTHER"),
            ("before dawn", "ENTITY", None, "OTHER"),
            ("Pushback is forbidden", "EVENT", "W2", "ACTION"),
            ("both wings are de-iced", "STATE_OR_FACET", "W1", "STATE"),
            ("Notify the tower", "EVENT", "W3", "COMMUNICATION"),
            ("the tower", "ENTITY", None, "OTHER"),
            ("either wing is skipped", "STATE_OR_FACET", "W4", "STATE"),
        ],
        "normative_edges": [
            ["W1", "W2", ["STATE_GATE", "PRECONDITION"], "Pushback is forbidden until both wings are de-iced"],
            ["W4", "W3", ["STATE_GATE", "RESPONSE"], "Notify the tower if either wing is skipped"],
        ],
        "related_pairs": [["W1", "W4"]],
        "ambiguous_pairs": [],
        "notes": "negation via 'forbidden until'; nominalization-subject prohibition clause; outcome state 'either wing is skipped' own cid; conditional communication.",
    },
    {
        "case_id": "l_funicular",
        "domain": "funicular railway",
        "family": "l_only_if_unless_same_state",
        "policy": "Run the funicular only if the brake test is passed. "
                  "Perform the brake test each morning. Do not carry "
                  "passengers unless the brakes have passed the test.",
        "tools": [
            {"name": "perform_brake_test", "description": "Performs one brake test on the funicular.", "input": {"car_id": "string"}, "output": {"passed": "boolean"}},
            {"name": "run_funicular", "description": "Runs the funicular for one trip.", "input": {"car_id": "string"}, "output": {"status": "string"}},
            {"name": "board_passengers", "description": "Boards one group of passengers.", "input": {"group_id": "string"}, "output": {"status": "string"}},
            {"name": "read_brake_log", "description": "Reads the brake test log of the funicular.", "input": {"car_id": "string"}, "output": {"last_passed": "string"}},
        ],
        "mentions": [
            ("Run the funicular", "EVENT", "R1", "ACTION"),
            ("the funicular", "ENTITY", None, "OTHER"),
            ("the brake test is passed", "STATE_OR_FACET", "R3", "STATE"),
            ("Perform the brake test", "CHECK", "R2", "CHECK"),
            ("the brake test", "ENTITY", None, "OTHER"),
            ("each morning", "ENTITY", None, "OTHER"),
            ("carry passengers", "EVENT", "R4", "ACTION"),
            ("the brakes have passed the test", "STATE_OR_FACET", "R3", "STATE"),
            ("the brakes", "ENTITY", None, "OTHER"),
        ],
        "normative_edges": [
            ["R3", "R1", ["STATE_GATE", "PRECONDITION"], "Run the funicular only if the brake test is passed"],
            ["R3", "R4", ["EXCEPTION", "STATE_GATE"], "Do not carry passengers unless the brakes have passed the test"],
        ],
        "related_pairs": [["R2", "R3"]],
        "ambiguous_pairs": [],
        "notes": "same passed-state gates two different actions via only-if and unless, with two different surface forms of the state; negated imperative mention without 'Do not'.",
    },
    {
        "case_id": "l_algae",
        "domain": "algae bioreactor",
        "family": "l_or_alternatives_threshold",
        "policy": "Purge the reactor if the cell density exceeds 40 units. "
                  "Harvest the algae or dilute the medium within one hour of "
                  "the purge. The harvest log records either action.",
        "tools": [
            {"name": "purge_reactor", "description": "Purges one algae reactor.", "input": {"reactor_id": "string"}, "output": {"status": "string"}},
            {"name": "harvest_algae", "description": "Harvests the algae from one reactor.", "input": {"reactor_id": "string"}, "output": {"grams": "number"}},
            {"name": "dilute_medium", "description": "Dilutes the medium of one reactor.", "input": {"reactor_id": "string"}, "output": {"volume_l": "number"}},
            {"name": "read_density_meter", "description": "Reads the density meter of one reactor.", "input": {"reactor_id": "string"}, "output": {"units": "number"}},
        ],
        "mentions": [
            ("Purge the reactor", "EVENT", "A1", "ACTION"),
            ("the reactor", "ENTITY", None, "OTHER"),
            ("the cell density exceeds 40 units", "STATE_OR_FACET", "A2", "STATE"),
            ("Harvest the algae", "EVENT", "A3", "ACTION"),
            ("the algae", "ENTITY", None, "OTHER"),
            ("dilute the medium", "EVENT", "A4", "ACTION"),
            ("the medium", "ENTITY", None, "OTHER"),
            ("one hour", "ENTITY", None, "OTHER"),
            ("the purge", "EVENT_REFERENCE", "A1", "REFERENCE_TO_EVENT"),
            ("The harvest log", "ARTIFACT", None, "OTHER"),
            ("either action", "EVENT_REFERENCE", None, "REFERENCE_TO_EVENT"),
        ],
        "normative_edges": [
            ["A2", "A1", ["STATE_GATE"], "Purge the reactor if the cell density exceeds 40 units"],
            ["A1", "A3", ["RESPONSE", "ORDER_BEFORE"], "Harvest the algae or dilute the medium within one hour of the purge"],
            ["A1", "A4", ["RESPONSE", "ORDER_BEFORE"], "Harvest the algae or dilute the medium within one hour of the purge"],
        ],
        "related_pairs": [],
        "ambiguous_pairs": [],
        "notes": "OR alternatives share the antecedent but get NO edge between them (F5 convention); numeric threshold; artifact-subject 'records either action' junk class.",
    },
    {
        "case_id": "l_bloodbank",
        "domain": "blood bank plasma",
        "family": "l_temporal_window_unless_record",
        "policy": "Collect each plasma donation. Chill the plasma within six "
                  "hours of collection. Discard the unit unless it is "
                  "chilled in time. Record the discard in the wastage file.",
        "tools": [
            {"name": "collect_plasma", "description": "Collects one plasma donation.", "input": {"donor_id": "string"}, "output": {"unit_id": "string"}},
            {"name": "chill_plasma", "description": "Chills one plasma unit.", "input": {"unit_id": "string"}, "output": {"temp_c": "number"}},
            {"name": "discard_unit", "description": "Discards one plasma unit.", "input": {"unit_id": "string"}, "output": {"status": "string"}},
            {"name": "record_wastage", "description": "Records one discard in the wastage file.", "input": {"unit_id": "string"}, "output": {"entry_id": "string"}},
        ],
        "mentions": [
            ("Collect each plasma donation", "EVENT", "P0", "ACTION"),
            ("each plasma donation", "ENTITY", None, "OTHER"),
            ("Chill the plasma", "EVENT", "P1", "ACTION"),
            ("the plasma", "ENTITY", None, "OTHER"),
            ("six hours", "ENTITY", None, "OTHER"),
            ("collection", "EVENT_REFERENCE", "P0", "REFERENCE_TO_EVENT"),
            ("Discard the unit", "EVENT", "P2", "ACTION"),
            ("the unit", "ENTITY", None, "OTHER"),
            ("it is chilled in time", "STATE_OR_FACET", "P1", "STATE"),
            ("Record the discard", "EVENT", "P3", "RECORD"),
            ("the discard", "EVENT_REFERENCE", "P2", "REFERENCE_TO_EVENT"),
            ("the wastage file", "ARTIFACT", None, "OTHER"),
        ],
        "normative_edges": [
            ["P0", "P1", ["ORDER_BEFORE"], "Chill the plasma within six hours of collection"],
            ["P1", "P2", ["EXCEPTION", "STATE_GATE"], "Discard the unit unless it is chilled in time"],
            ["P2", "P3", ["RESPONSE", "ORDER_BEFORE"], "Record the discard in the wastage file"],
        ],
        "related_pairs": [],
        "ambiguous_pairs": [],
        "notes": "temporal window ('within X of nominalization'); unless-exception over pronoun passive facet; record-after-action chain.",
    },
    {
        "case_id": "l_artillery",
        "domain": "artillery range safety",
        "family": "l_only_if_coordinated_state_gates",
        "policy": "Zero the guns before live firing. Live firing is "
                  "permitted only if the range is clear and the red flag is "
                  "hoisted. Lower the flag if firing is cancelled.",
        "tools": [
            {"name": "zero_guns", "description": "Zeros one set of guns.", "input": {"battery_id": "string"}, "output": {"offset": "string"}},
            {"name": "fire_live_rounds", "description": "Fires live rounds on one range.", "input": {"range_id": "string"}, "output": {"rounds": "number"}},
            {"name": "hoist_red_flag", "description": "Hoists the red flag on one range.", "input": {"range_id": "string"}, "output": {"status": "string"}},
            {"name": "lower_flag", "description": "Lowers the flag on one range.", "input": {"range_id": "string"}, "output": {"status": "string"}},
        ],
        "mentions": [
            ("Zero the guns", "EVENT", "Z1", "ACTION"),
            ("the guns", "ENTITY", None, "OTHER"),
            ("Live firing is permitted", "EVENT", "Z2", "ACTION"),
            ("the range is clear", "STATE_OR_FACET", "Z3", "STATE"),
            ("the range", "ENTITY", None, "OTHER"),
            ("the red flag is hoisted", "STATE_OR_FACET", "Z4", "STATE"),
            ("the red flag", "ENTITY", None, "OTHER"),
            ("Lower the flag", "EVENT", "Z5", "ACTION"),
            ("firing is cancelled", "STATE_OR_FACET", "Z6", "STATE"),
        ],
        "normative_edges": [
            ["Z1", "Z2", ["ORDER_BEFORE"], "Zero the guns before live firing"],
            ["Z3", "Z2", ["STATE_GATE", "PRECONDITION"], "Live firing is permitted only if the range is clear and the red flag is hoisted"],
            ["Z4", "Z2", ["STATE_GATE", "PRECONDITION"], "Live firing is permitted only if the range is clear and the red flag is hoisted"],
            ["Z6", "Z5", ["STATE_GATE", "RESPONSE"], "Lower the flag if firing is cancelled"],
        ],
        "related_pairs": [["Z2", "Z6"]],
        "ambiguous_pairs": [],
        "notes": "nominalization-subject permission clause; coordinated state gates; cancellation outcome state own cid; flag hoisted state has no active mention.",
    },
    {
        "case_id": "l_olive",
        "domain": "olive oil mill",
        "family": "l_gerund_pronoun_descriptive",
        "policy": "Press the olives within two days of harvest. Wash the "
                  "olives before pressing them. The press house is a listed "
                  "building.",
        "tools": [
            {"name": "wash_olives", "description": "Washes one crate of olives.", "input": {"crate_id": "string"}, "output": {"status": "string"}},
            {"name": "press_olives", "description": "Presses one crate of olives.", "input": {"crate_id": "string"}, "output": {"litres": "number"}},
            {"name": "record_batch", "description": "Records one pressing batch in the mill book.", "input": {"crate_id": "string"}, "output": {"entry_id": "string"}},
            {"name": "read_moisture", "description": "Reads the moisture of one crate of olives.", "input": {"crate_id": "string"}, "output": {"pct": "number"}},
        ],
        "mentions": [
            ("Press the olives", "EVENT", "V1", "ACTION"),
            ("the olives", "ENTITY", None, "OTHER"),
            ("two days", "ENTITY", None, "OTHER"),
            ("harvest", "EVENT_REFERENCE", None, "REFERENCE_TO_EVENT"),
            ("Wash the olives", "EVENT", "V2", "ACTION"),
            ("pressing them", "EVENT_REFERENCE", "V1", "REFERENCE_TO_EVENT"),
            ("The press house", "ENTITY", None, "OTHER"),
            ("a listed building", "ENTITY", None, "OTHER"),
        ],
        "normative_edges": [
            ["V2", "V1", ["ORDER_BEFORE", "PRECONDITION"], "Wash the olives before pressing them"],
        ],
        "related_pairs": [],
        "ambiguous_pairs": [],
        "notes": "gerund+pronoun reference; descriptive non-policy final sentence; 'harvest' referenced-only nominalization (no cid, F5 junk-class convention for reference-only nominals).",
    },
    {
        "case_id": "l_snowroute",
        "domain": "snow route maintenance",
        "family": "l_same_predicate_roads_completion",
        "policy": "Plough the north road before 06:00. Plough the south road "
                  "after the north road is cleared. Grit both roads once "
                  "ploughing is complete.",
        "tools": [
            {"name": "plough_road", "description": "Ploughs one road.", "input": {"road_id": "string"}, "output": {"status": "string"}},
            {"name": "grit_road", "description": "Grits one road.", "input": {"road_id": "string"}, "output": {"kg": "number"}},
            {"name": "check_road_status", "description": "Reads the clearance status of one road.", "input": {"road_id": "string"}, "output": {"cleared": "boolean"}},
            {"name": "log_plough", "description": "Writes one ploughing entry in the route log.", "input": {"road_id": "string"}, "output": {"entry_id": "string"}},
        ],
        "mentions": [
            ("Plough the north road", "EVENT", "N1", "ACTION"),
            ("the north road", "ENTITY", None, "OTHER"),
            ("Plough the south road", "EVENT", "N2", "ACTION"),
            ("the south road", "ENTITY", None, "OTHER"),
            ("the north road is cleared", "STATE_OR_FACET", "N3", "STATE"),
            ("Grit both roads", "EVENT", "N4", "ACTION"),
            ("both roads", "ENTITY", None, "OTHER"),
            ("ploughing is complete", "STATE_OR_FACET", "N5", "STATE"),
        ],
        "normative_edges": [
            ["N3", "N2", ["STATE_GATE", "PRECONDITION"], "Plough the south road after the north road is cleared"],
            ["N5", "N4", ["STATE_GATE"], "Grit both roads once ploughing is complete"],
        ],
        "related_pairs": [["N1", "N3"], ["N1", "N5"], ["N2", "N5"]],
        "ambiguous_pairs": [],
        "notes": "same predicate on two objects; result state via a DIFFERENT predicate ('is cleared' vs 'Plough') own cid; completion state of both ploughings; multiple operations.",
    },
    {
        "case_id": "l_roastery",
        "domain": "coffee roastery",
        "family": "l_may_permission_negation_record",
        "policy": "Roast the beans at 205 degrees. Cooling may begin once the "
                  "beans are roasted. Do not open the drum before cooling is "
                  "finished. The roast sheet is filed by the roaster.",
        "tools": [
            {"name": "roast_beans", "description": "Roasts one drum of beans.", "input": {"drum_id": "string"}, "output": {"status": "string"}},
            {"name": "open_drum", "description": "Opens one roaster drum.", "input": {"drum_id": "string"}, "output": {"status": "string"}},
            {"name": "file_roast_sheet", "description": "Files one roast sheet.", "input": {"drum_id": "string"}, "output": {"entry_id": "string"}},
            {"name": "read_drum_temp", "description": "Reads the drum temperature of one roaster.", "input": {"drum_id": "string"}, "output": {"temp_c": "number"}},
        ],
        "mentions": [
            ("Roast the beans", "EVENT", "K1", "ACTION"),
            ("the beans", "ENTITY", None, "OTHER"),
            ("205 degrees", "ENTITY", None, "OTHER"),
            ("Cooling may begin", "EVENT", "K2", "ACTION"),
            ("the beans are roasted", "STATE_OR_FACET", "K1", "STATE"),
            ("open the drum", "EVENT", "K3", "ACTION"),
            ("the drum", "ENTITY", None, "OTHER"),
            ("cooling is finished", "STATE_OR_FACET", "K4", "STATE"),
            ("The roast sheet is filed by the roaster", "EVENT", "K5", "RECORD"),
            ("the roaster", "ENTITY", None, "OTHER"),
        ],
        "normative_edges": [
            ["K1", "K2", ["STATE_GATE", "PRECONDITION"], "Cooling may begin once the beans are roasted"],
            ["K4", "K3", ["STATE_GATE"], "Do not open the drum before cooling is finished"],
        ],
        "related_pairs": [["K2", "K4"], ["K1", "K5"]],
        "ambiguous_pairs": [],
        "notes": "may-permission via nominalization subject; negated order; completion state own cid; artifact-subject recording passive IS a gold RECORD event here (F6 convention change vs F5 r_fountain).",
    },
]

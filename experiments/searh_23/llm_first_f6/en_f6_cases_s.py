"""F6 sealed suite — GROUP S (reference & identity stress), compact gold.

See en_f6_cases_m.py header for the mention tuple format and the F6
gold conventions.
"""

S_CASES = [
    {
        "case_id": "s_telegraph",
        "domain": "harbour telegraph soundings",
        "family": "s_quoted_reported_communication",
        "policy": "The harbormaster orders the crew to sound the depth every "
                  "hour. Sound the depth as ordered. Log each sounding in "
                  "the tide book.",
        "tools": [
            {"name": "sound_depth", "description": "Sounds the depth at one station.", "input": {"station_id": "string"}, "output": {"metres": "number"}},
            {"name": "log_sounding", "description": "Writes one sounding in the tide book.", "input": {"station_id": "string"}, "output": {"entry_id": "string"}},
            {"name": "relay_order", "description": "Relays one order from the harbormaster.", "input": {"order_id": "string"}, "output": {"status": "string"}},
            {"name": "read_tide_book", "description": "Reads one tide book entry.", "input": {"station_id": "string"}, "output": {"metres": "number"}},
        ],
        "mentions": [
            ("The harbormaster orders the crew to sound the depth", "EVENT", "T0", "COMMUNICATION", {"embeds": "sound the depth"}),
            ("The harbormaster", "ENTITY", None, "OTHER"),
            ("the crew", "ENTITY", None, "OTHER"),
            ("sound the depth", "EVENT", "T1", "ACTION"),
            ("every hour", "ENTITY", None, "OTHER"),
            ("Sound the depth", "EVENT", "T1", "ACTION"),
            ("as ordered", "EVENT_REFERENCE", "T0", "REFERENCE_TO_EVENT"),
            ("Log each sounding", "EVENT", "T2", "RECORD"),
            ("each sounding", "EVENT_REFERENCE", "T1", "REFERENCE_TO_EVENT"),
            ("the tide book", "ARTIFACT", None, "OTHER"),
        ],
        "normative_edges": [
            ["T1", "T2", ["RESPONSE", "ORDER_BEFORE"], "Log each sounding in the tide book"],
        ],
        "related_pairs": [["T0", "T1"]],
        "ambiguous_pairs": [],
        "notes": "quoted/reported action: the embedded 'sound the depth' shares cid with the direct imperative (reported == prescribed action, hard SAME pair); communication event with 'as ordered' reference to it.",
    },
    {
        "case_id": "s_cheese",
        "domain": "cheese vat house",
        "family": "s_anaphora_repetition_record",
        "policy": "Coagulate the milk in vat 3. Repeat this step for vat 4. "
                  "Add the cultures only after each coagulation is complete. "
                  "The cheese maker records every coagulation.",
        "tools": [
            {"name": "coagulate_milk", "description": "Coagulates the milk in one vat.", "input": {"vat_id": "string"}, "output": {"status": "string"}},
            {"name": "add_cultures", "description": "Adds cultures to one vat.", "input": {"vat_id": "string"}, "output": {"status": "string"}},
            {"name": "record_coagulation", "description": "Records one coagulation in the vat log.", "input": {"vat_id": "string"}, "output": {"entry_id": "string"}},
            {"name": "read_vat_temp", "description": "Reads the temperature of one vat.", "input": {"vat_id": "string"}, "output": {"temp_c": "number"}},
        ],
        "mentions": [
            ("Coagulate the milk in vat 3", "EVENT", "H1", "ACTION"),
            ("the milk", "ENTITY", None, "OTHER"),
            ("vat 3", "ENTITY", None, "OTHER"),
            ("Repeat this step", "EVENT", "H1b", "ACTION"),
            ("this step", "EVENT_REFERENCE", "H1", "REFERENCE_TO_EVENT"),
            ("vat 4", "ENTITY", None, "OTHER"),
            ("Add the cultures", "EVENT", "H2", "ACTION"),
            ("the cultures", "ENTITY", None, "OTHER"),
            ("each coagulation is complete", "STATE_OR_FACET", "H4", "STATE"),
            ("The cheese maker records every coagulation", "EVENT", "H3", "RECORD"),
            ("The cheese maker", "ENTITY", None, "OTHER"),
            ("every coagulation", "EVENT_REFERENCE", "H1", "REFERENCE_TO_EVENT"),
        ],
        "normative_edges": [
            ["H4", "H2", ["STATE_GATE", "PRECONDITION"], "Add the cultures only after each coagulation is complete"],
        ],
        "related_pairs": [["H1", "H1b"], ["H1", "H4"], ["H1b", "H4"], ["H1", "H3"]],
        "ambiguous_pairs": [],
        "notes": "'this step' anaphora; repetition clause = separate occurrence cid (RELATED); human-subject recording clause; plural nominal reference covers both occurrences.",
    },
    {
        "case_id": "s_elevator",
        "domain": "elevator maintenance",
        "family": "s_cross_sentence_passive_chain",
        "policy": "Service the elevator motor quarterly. The inspector signs "
                  "the service report. Renew the certificate only after the "
                  "report is signed. Run the car only while the certificate "
                  "is current.",
        "tools": [
            {"name": "service_motor", "description": "Services one elevator motor.", "input": {"car_id": "string"}, "output": {"status": "string"}},
            {"name": "sign_service_report", "description": "Signs one service report.", "input": {"report_id": "string"}, "output": {"status": "string"}},
            {"name": "renew_certificate", "description": "Renews the service certificate of one elevator.", "input": {"car_id": "string"}, "output": {"valid_until": "string"}},
            {"name": "run_elevator", "description": "Runs one elevator car.", "input": {"car_id": "string"}, "output": {"status": "string"}},
        ],
        "mentions": [
            ("Service the elevator motor", "EVENT", "E1", "ACTION"),
            ("the elevator motor", "ENTITY", None, "OTHER"),
            ("The inspector", "ENTITY", None, "OTHER"),
            ("signs the service report", "EVENT", "E2", "RECORD"),
            ("the service report", "ARTIFACT", None, "OTHER"),
            ("Renew the certificate", "EVENT", "E4", "ACTION"),
            ("the certificate", "ENTITY", None, "OTHER"),
            ("the report is signed", "STATE_OR_FACET", "E2", "STATE"),
            ("Run the car", "EVENT", "E5", "ACTION"),
            ("the car", "ENTITY", None, "OTHER"),
            ("the certificate is current", "STATE_OR_FACET", "E6", "STATE"),
        ],
        "normative_edges": [
            ["E2", "E4", ["PRECONDITION", "ORDER_BEFORE"], "Renew the certificate only after the report is signed"],
            ["E6", "E5", ["STATE_GATE"], "Run the car only while the certificate is current"],
        ],
        "related_pairs": [["E1", "E2"], ["E4", "E6"]],
        "ambiguous_pairs": [],
        "notes": "cross-sentence passive facet ('the report is signed' shares the signing cid); 'only while' duration gate; currency state own cid; signing typed RECORD.",
    },
    {
        "case_id": "s_herbarium",
        "domain": "herbarium specimen mounting",
        "family": "s_hypothetical_conditional",
        "policy": "Mount each herbarium sheet. If a specimen is damaged, "
                  "photograph it before mounting. Report any damage to the "
                  "registrar.",
        "tools": [
            {"name": "mount_sheet", "description": "Mounts one herbarium sheet.", "input": {"sheet_id": "string"}, "output": {"status": "string"}},
            {"name": "photograph_specimen", "description": "Photographs one specimen.", "input": {"sheet_id": "string"}, "output": {"photo_id": "string"}},
            {"name": "report_damage", "description": "Reports one damaged specimen to the registrar.", "input": {"sheet_id": "string"}, "output": {"report_id": "string"}},
            {"name": "read_specimen_label", "description": "Reads the label of one specimen sheet.", "input": {"sheet_id": "string"}, "output": {"species": "string"}},
        ],
        "mentions": [
            ("Mount each herbarium sheet", "EVENT", "U1", "ACTION"),
            ("each herbarium sheet", "ENTITY", None, "OTHER"),
            ("a specimen is damaged", "STATE_OR_FACET", "U2", "STATE"),
            ("a specimen", "ENTITY", None, "OTHER"),
            ("photograph it", "EVENT", "U3", "ACTION"),
            ("mounting", "EVENT_REFERENCE", "U1", "REFERENCE_TO_EVENT"),
            ("Report any damage", "EVENT", "U4", "COMMUNICATION"),
            ("any damage", "EVENT_REFERENCE", "U2", "REFERENCE_TO_EVENT"),
            ("the registrar", "ENTITY", None, "OTHER"),
        ],
        "normative_edges": [
            ["U2", "U3", ["STATE_GATE"], "If a specimen is damaged, photograph it before mounting"],
            ["U3", "U1", ["ORDER_BEFORE"], "photograph it before mounting"],
        ],
        "related_pairs": [["U2", "U4"]],
        "ambiguous_pairs": [],
        "notes": "hypothetical/conditional action with pronoun object; bare gerund reference; damage-state referenced by a communication event.",
    },
    {
        "case_id": "s_radio",
        "domain": "radio station transmissions",
        "family": "s_confirmation_communication",
        "policy": "Broadcast the weather bulletin at noon. Confirm that the "
                  "bulletin was transmitted. Notify the regulator if "
                  "confirmation fails.",
        "tools": [
            {"name": "broadcast_bulletin", "description": "Broadcasts one weather bulletin.", "input": {"bulletin_id": "string"}, "output": {"status": "string"}},
            {"name": "confirm_transmission", "description": "Confirms one bulletin transmission.", "input": {"bulletin_id": "string"}, "output": {"confirmed": "boolean"}},
            {"name": "notify_regulator", "description": "Notifies the regulator about one station.", "input": {"station_id": "string"}, "output": {"status": "string"}},
            {"name": "read_transmitter_log", "description": "Reads the transmitter log of one station.", "input": {"station_id": "string"}, "output": {"last_tx": "string"}},
        ],
        "mentions": [
            ("Broadcast the weather bulletin", "EVENT", "M1", "COMMUNICATION"),
            ("the weather bulletin", "ENTITY", None, "OTHER"),
            ("at noon", "ENTITY", None, "OTHER"),
            ("Confirm that the bulletin was transmitted", "CHECK", "M2", "CHECK", {"embeds": "the bulletin was transmitted"}),
            ("the bulletin was transmitted", "STATE_OR_FACET", "M1", "STATE"),
            ("Notify the regulator", "EVENT", "M3", "COMMUNICATION"),
            ("the regulator", "ENTITY", None, "OTHER"),
            ("confirmation fails", "STATE_OR_FACET", "M4", "STATE"),
        ],
        "normative_edges": [
            ["M4", "M3", ["STATE_GATE", "RESPONSE"], "Notify the regulator if confirmation fails"],
        ],
        "related_pairs": [["M1", "M2"], ["M2", "M4"]],
        "ambiguous_pairs": [],
        "notes": "directive confirmation example; embedded state expressed with a SYNONYM predicate ('transmitted' vs 'Broadcast') sharing the cid (synonym-voice facet); failure outcome state own cid.",
    },
    {
        "case_id": "s_fishery",
        "domain": "river fishery survey",
        "family": "s_entity_ids_forward_reference",
        "policy": "Weigh fish 44 before tagging it. Tag fish 44 at the "
                  "upstream station. Tag fish 45 only at the downstream "
                  "station. Record the weight of fish 44.",
        "tools": [
            {"name": "weigh_fish", "description": "Weighs one fish.", "input": {"fish_id": "string"}, "output": {"grams": "number"}},
            {"name": "tag_fish", "description": "Tags one fish.", "input": {"fish_id": "string"}, "output": {"tag_id": "string"}},
            {"name": "record_weight", "description": "Records the weight of one fish.", "input": {"fish_id": "string"}, "output": {"entry_id": "string"}},
            {"name": "read_scale", "description": "Reads the scale at one station.", "input": {"station_id": "string"}, "output": {"grams": "number"}},
        ],
        "mentions": [
            ("Weigh fish 44", "CHECK", "W1", "CHECK"),
            ("fish 44", "ENTITY", None, "OTHER"),
            ("tagging it", "EVENT_REFERENCE", "T1", "REFERENCE_TO_EVENT"),
            ("Tag fish 44", "EVENT", "T1", "ACTION"),
            ("the upstream station", "ENTITY", None, "OTHER"),
            ("Tag fish 45", "EVENT", "T2", "ACTION"),
            ("fish 45", "ENTITY", None, "OTHER"),
            ("the downstream station", "ENTITY", None, "OTHER"),
            ("Record the weight", "EVENT", "R1", "RECORD"),
            ("the weight", "EVENT_REFERENCE", "W1", "REFERENCE_TO_EVENT"),
        ],
        "normative_edges": [
            ["W1", "T1", ["ORDER_BEFORE", "PRECONDITION"], "Weigh fish 44 before tagging it"],
            ["W1", "R1", ["RESPONSE", "ORDER_BEFORE"], "Record the weight of fish 44"],
        ],
        "related_pairs": [],
        "ambiguous_pairs": [],
        "notes": "entity IDs that matter (fish 44 vs fish 45, same predicate -> DIFFERENT events, no relation); forward gerund reference ('tagging it' before the imperative appears).",
    },
    {
        "case_id": "s_incubator",
        "domain": "laboratory incubator",
        "family": "s_check_of_state_vs_action",
        "policy": "Warm the incubator to 37 degrees. Check that the incubator "
                  "is warm before loading the samples.",
        "tools": [
            {"name": "warm_incubator", "description": "Warms one incubator to a set temperature.", "input": {"incubator_id": "string", "temp_c": "number"}, "output": {"status": "string"}},
            {"name": "load_samples", "description": "Loads one rack of samples into the incubator.", "input": {"incubator_id": "string"}, "output": {"status": "string"}},
            {"name": "check_incubator_temp", "description": "Reads the temperature of one incubator.", "input": {"incubator_id": "string"}, "output": {"temp_c": "number"}},
            {"name": "log_temperature", "description": "Records one temperature reading in the incubator log.", "input": {"incubator_id": "string"}, "output": {"entry_id": "string"}},
        ],
        "mentions": [
            ("Warm the incubator", "EVENT", "I1", "ACTION"),
            ("the incubator", "ENTITY", None, "OTHER"),
            ("37 degrees", "ENTITY", None, "OTHER"),
            ("Check that the incubator is warm", "CHECK", "I2", "CHECK", {"embeds": "the incubator is warm"}),
            ("the incubator is warm", "STATE_OR_FACET", "I3", "STATE"),
            ("loading the samples", "EVENT", "I4", "ACTION"),
            ("the samples", "ENTITY", None, "OTHER"),
        ],
        "normative_edges": [
            ["I3", "I4", ["STATE_GATE", "PRECONDITION"], "Check that the incubator is warm before loading the samples"],
        ],
        "related_pairs": [["I1", "I3"], ["I1", "I2"], ["I2", "I3"]],
        "ambiguous_pairs": [],
        "notes": "directive class 'check of a state vs execution of the action producing that state': warming (I1) vs warm state (I3) vs check-of-state (I2); the gate endpoint is the STATE (F5 r_ewaste convention).",
    },
    {
        "case_id": "s_radar",
        "domain": "radar array calibration",
        "family": "s_repetition_completion",
        "policy": "Calibrate the radar array each Monday. Repeat the "
                  "calibration if drift is detected. Power the array only "
                  "after the second calibration is complete.",
        "tools": [
            {"name": "calibrate_array", "description": "Calibrates one radar array.", "input": {"array_id": "string"}, "output": {"status": "string"}},
            {"name": "repeat_calibration", "description": "Repeats one calibration run.", "input": {"array_id": "string"}, "output": {"status": "string"}},
            {"name": "power_array", "description": "Powers one radar array.", "input": {"array_id": "string"}, "output": {"status": "string"}},
            {"name": "read_drift_report", "description": "Reads the drift report of one array.", "input": {"array_id": "string"}, "output": {"drift_mm": "number"}},
        ],
        "mentions": [
            ("Calibrate the radar array", "EVENT", "D1", "ACTION"),
            ("the radar array", "ENTITY", None, "OTHER"),
            ("each Monday", "ENTITY", None, "OTHER"),
            ("Repeat the calibration", "EVENT", "D2", "ACTION"),
            ("the calibration", "EVENT_REFERENCE", "D1", "REFERENCE_TO_EVENT"),
            ("drift is detected", "STATE_OR_FACET", "D3", "STATE"),
            ("Power the array", "EVENT", "D4", "ACTION"),
            ("the array", "ENTITY", None, "OTHER"),
            ("the second calibration is complete", "STATE_OR_FACET", "D5", "STATE"),
        ],
        "normative_edges": [
            ["D3", "D2", ["STATE_GATE"], "Repeat the calibration if drift is detected"],
            ["D5", "D4", ["STATE_GATE"], "Power the array only after the second calibration is complete"],
        ],
        "related_pairs": [["D1", "D2"], ["D2", "D5"]],
        "ambiguous_pairs": [],
        "notes": "repetition = separate occurrence (RELATED); ordinal 'second' marks the repeat; completion state of the REPEAT gates power-on; detection state without an explicit detect action.",
    },
]

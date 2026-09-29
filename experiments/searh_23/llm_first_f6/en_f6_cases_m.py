"""F6 sealed suite — GROUP M (mention-form mechanics), compact gold.

Mention tuple: (span, pipeline_type, cid, sem_type [, extra_dict])
  pipeline_type: EVENT | CHECK | STATE_OR_FACET | EVENT_REFERENCE | ARTIFACT | ENTITY
  sem_type:      ACTION | CHECK | STATE | RECORD | COMMUNICATION |
                 REFERENCE_TO_EVENT | OTHER
  extra_dict:    {"embeds": "<span of embedded mention>"} for nested events.

F6 gold conventions (see f6_manifest.json):
  - passive voice facet shares the action cid (F5 convention kept);
  - adjectival/result/completion/outcome states get their OWN cid (RELATED);
  - action / check-of-action / recording are distinct cids (F5 kept);
  - repetition ('again', 'repeat', ordinal second) = separate cid (F5 kept);
  - nested CHECK/RECORD/COMMUNICATION clauses keep BOTH the outer mention
    and the embedded clause mention (NEW in F6, directive 3.2);
  - recording clauses ('X is logged/filed/signed by Y') are RECORD events
    with their own cid (CONVENTION CHANGE vs F5, directive 3.2);
  - outcome/failure/cancellation/skipping states get their own cid (NEW);
  - temporal PPs with bare deverbal heads are not annotated; plain
    temporal NPs ('before dawn', 'each March') are ENTITY mentions;
  - entity NPs listed once per distinct surface form.
"""

M_CASES = [
    {
        "case_id": "m_tram",
        "domain": "tram depot rail grinding",
        "family": "m_active_passive_nominal_record",
        "policy": "Grind the rail joints on line 2. Trams may pass once the "
                  "joints have been ground. Grinding of the joints is logged "
                  "in the depot ledger. The depot ledger is a bound book.",
        "tools": [
            {"name": "grind_rail_joints", "description": "Grinds the rail joints of one tram line.", "input": {"line_id": "string"}, "output": {"status": "string"}},
            {"name": "run_tram_service", "description": "Runs one tram across the line.", "input": {"tram_id": "string"}, "output": {"status": "string"}},
            {"name": "log_grinding", "description": "Writes one grinding entry into the depot ledger.", "input": {"line_id": "string"}, "output": {"entry_id": "string"}},
            {"name": "inspect_rail_wear", "description": "Reads the wear level of the rail joints.", "input": {"line_id": "string"}, "output": {"wear_mm": "number"}},
        ],
        "mentions": [
            ("Grind the rail joints", "EVENT", "G1", "ACTION"),
            ("the rail joints", "ENTITY", None, "OTHER"),
            ("line 2", "ENTITY", None, "OTHER"),
            ("Trams may pass", "EVENT", "G2", "ACTION"),
            ("the joints have been ground", "STATE_OR_FACET", "G1", "STATE"),
            ("Grinding of the joints", "EVENT_REFERENCE", "G1", "REFERENCE_TO_EVENT"),
            ("Grinding of the joints is logged in the depot ledger", "EVENT", "G3", "RECORD", {"embeds": "Grinding of the joints"}),
            ("The depot ledger", "ARTIFACT", None, "OTHER"),
            ("a bound book", "ENTITY", None, "OTHER"),
        ],
        "normative_edges": [
            ["G1", "G2", ["STATE_GATE", "PRECONDITION"], "Trams may pass once the joints have been ground"],
        ],
        "related_pairs": [["G1", "G3"]],
        "ambiguous_pairs": [],
        "notes": "active->passive->nominalization chain; recording clause as RECORD event (nested reference); final sentence is descriptive non-policy.",
    },
    {
        "case_id": "m_balloon",
        "domain": "hot air balloon launch",
        "family": "m_result_state_coordination",
        "policy": "Inflate the envelope before sunrise. The envelope must be "
                  "taut. Launch the balloon only after the envelope is taut "
                  "and the burner is lit.",
        "tools": [
            {"name": "inflate_envelope", "description": "Inflates one balloon envelope.", "input": {"balloon_id": "string"}, "output": {"status": "string"}},
            {"name": "light_burner", "description": "Lights the burner of one balloon.", "input": {"balloon_id": "string"}, "output": {"status": "string"}},
            {"name": "launch_balloon", "description": "Launches one balloon.", "input": {"balloon_id": "string"}, "output": {"status": "string"}},
            {"name": "read_envelope_pressure", "description": "Reads the pressure gauge of one envelope.", "input": {"balloon_id": "string"}, "output": {"pressure": "number"}},
        ],
        "mentions": [
            ("Inflate the envelope", "EVENT", "B1", "ACTION"),
            ("the envelope", "ENTITY", None, "OTHER"),
            ("before sunrise", "ENTITY", None, "OTHER"),
            ("The envelope must be taut", "STATE_OR_FACET", "B2", "STATE"),
            ("Launch the balloon", "EVENT", "B3", "ACTION"),
            ("the balloon", "ENTITY", None, "OTHER"),
            ("the envelope is taut", "STATE_OR_FACET", "B2", "STATE"),
            ("the burner is lit", "STATE_OR_FACET", "B4", "STATE"),
            ("the burner", "ENTITY", None, "OTHER"),
        ],
        "normative_edges": [
            ["B2", "B3", ["STATE_GATE", "PRECONDITION"], "Launch the balloon only after the envelope is taut and the burner is lit"],
            ["B4", "B3", ["STATE_GATE", "PRECONDITION"], "Launch the balloon only after the envelope is taut and the burner is lit"],
        ],
        "related_pairs": [["B1", "B2"]],
        "ambiguous_pairs": [],
        "notes": "adjectival result state own cid (RELATED to inflate); coordinated AND state gates; state-vs-action distinction.",
    },
    {
        "case_id": "m_dentallab",
        "domain": "dental laboratory sterilization",
        "family": "m_nominal_subject_artifact_flow",
        "policy": "Sterilization of the instruments is required before each "
                  "appointment. Autoclave the instruments at 134 degrees. "
                  "The autoclave printout confirms each sterilized tray. "
                  "Seat the patient only after the printout is filed.",
        "tools": [
            {"name": "autoclave_instruments", "description": "Sterilizes one instrument tray in the autoclave.", "input": {"tray_id": "string"}, "output": {"status": "string"}},
            {"name": "file_printout", "description": "Files one autoclave printout.", "input": {"tray_id": "string"}, "output": {"entry_id": "string"}},
            {"name": "seat_patient", "description": "Seats one patient in the chair.", "input": {"patient_id": "string"}, "output": {"status": "string"}},
            {"name": "read_printout", "description": "Reads one autoclave printout.", "input": {"tray_id": "string"}, "output": {"cycles": "number"}},
        ],
        "mentions": [
            ("Sterilization of the instruments", "EVENT_REFERENCE", "D1", "REFERENCE_TO_EVENT"),
            ("each appointment", "ENTITY", None, "OTHER"),
            ("Autoclave the instruments", "EVENT", "D1", "ACTION"),
            ("the instruments", "ENTITY", None, "OTHER"),
            ("134 degrees", "ENTITY", None, "OTHER"),
            ("The autoclave printout", "ARTIFACT", None, "OTHER"),
            ("each sterilized tray", "EVENT_REFERENCE", None, "REFERENCE_TO_EVENT"),
            ("Seat the patient", "EVENT", "D3", "ACTION"),
            ("the patient", "ENTITY", None, "OTHER"),
            ("the printout is filed", "STATE_OR_FACET", "D4", "STATE"),
        ],
        "normative_edges": [
            ["D4", "D3", ["STATE_GATE", "PRECONDITION"], "Seat the patient only after the printout is filed"],
        ],
        "related_pairs": [["D1", "D4"]],
        "ambiguous_pairs": [],
        "notes": "subject nominalization shares cid with the imperative (SAME_EVENT pair); artifact-subject 'confirms' sentence is the junk class (participle NP, no cid); artifact-filing state gates seating.",
    },
    {
        "case_id": "m_observatory",
        "domain": "observatory dome operation",
        "family": "m_check_vs_state_readout",
        "policy": "Open the dome only if the sky meter reads clear. Read the "
                  "sky meter before opening the dome. Record the reading in "
                  "the night report.",
        "tools": [
            {"name": "open_dome", "description": "Opens one observatory dome.", "input": {"dome_id": "string"}, "output": {"status": "string"}},
            {"name": "read_sky_meter", "description": "Reads one sky meter and returns the reading.", "input": {"meter_id": "string"}, "output": {"reading": "string"}},
            {"name": "write_night_report", "description": "Appends one entry to the night report.", "input": {"entry": "string"}, "output": {"entry_id": "string"}},
            {"name": "calibrate_sky_meter", "description": "Calibrates one sky meter.", "input": {"meter_id": "string"}, "output": {"status": "string"}},
        ],
        "mentions": [
            ("Open the dome", "EVENT", "O1", "ACTION"),
            ("the dome", "ENTITY", None, "OTHER"),
            ("the sky meter reads clear", "STATE_OR_FACET", "O2", "STATE"),
            ("the sky meter", "ENTITY", None, "OTHER"),
            ("Read the sky meter", "CHECK", "O3", "CHECK"),
            ("opening the dome", "EVENT_REFERENCE", "O1", "REFERENCE_TO_EVENT"),
            ("Record the reading", "EVENT", "O4", "RECORD"),
            ("the reading", "EVENT_REFERENCE", "O3", "REFERENCE_TO_EVENT"),
            ("the night report", "ARTIFACT", None, "OTHER"),
        ],
        "normative_edges": [
            ["O2", "O1", ["STATE_GATE", "PRECONDITION"], "Open the dome only if the sky meter reads clear"],
            ["O3", "O1", ["ORDER_BEFORE"], "Read the sky meter before opening the dome"],
        ],
        "related_pairs": [["O2", "O3"], ["O3", "O4"]],
        "ambiguous_pairs": [],
        "notes": "check-of-state vs state readout: 'the sky meter reads clear' (state O2) vs 'Read the sky meter' (check O3) - directive class 'check of a state vs execution of the action producing that state'; gerund reference; record flow.",
    },
    {
        "case_id": "m_mint",
        "domain": "mint coin striking",
        "family": "m_same_object_diff_predicates",
        "policy": "Weigh the coin blanks. Anneal the coin blanks. Strike the "
                  "coins only after both steps are complete.",
        "tools": [
            {"name": "weigh_blanks", "description": "Weighs one set of coin blanks.", "input": {"set_id": "string"}, "output": {"grams": "number"}},
            {"name": "anneal_blanks", "description": "Anneals one set of coin blanks.", "input": {"set_id": "string"}, "output": {"status": "string"}},
            {"name": "strike_coins", "description": "Strikes one batch of coins.", "input": {"batch_id": "string"}, "output": {"count": "number"}},
            {"name": "log_blank_weight", "description": "Records the weight of one set of coin blanks.", "input": {"set_id": "string"}, "output": {"entry_id": "string"}},
        ],
        "mentions": [
            ("Weigh the coin blanks", "CHECK", "M1", "CHECK"),
            ("the coin blanks", "ENTITY", None, "OTHER"),
            ("Anneal the coin blanks", "EVENT", "M2", "ACTION"),
            ("Strike the coins", "EVENT", "M3", "ACTION"),
            ("the coins", "ENTITY", None, "OTHER"),
            ("both steps are complete", "STATE_OR_FACET", "M4", "STATE"),
        ],
        "normative_edges": [
            ["M4", "M3", ["STATE_GATE", "PRECONDITION"], "Strike the coins only after both steps are complete"],
        ],
        "related_pairs": [["M1", "M4"], ["M2", "M4"]],
        "ambiguous_pairs": [],
        "notes": "same object under three different predicates (weigh/anneal/strike); elliptical plural state reference 'both steps'.",
    },
    {
        "case_id": "m_coral",
        "domain": "coral reef survey",
        "family": "m_same_predicate_diff_objects",
        "policy": "Tag the staghorn colonies before surveying the reef flat. "
                  "Tag the brain corals after the survey. Photograph every "
                  "tagged colony.",
        "tools": [
            {"name": "tag_colony", "description": "Tags one coral colony.", "input": {"colony_id": "string"}, "output": {"tag_id": "string"}},
            {"name": "survey_reef", "description": "Surveys one section of reef flat.", "input": {"section_id": "string"}, "output": {"report": "string"}},
            {"name": "photograph_colony", "description": "Photographs one coral colony.", "input": {"colony_id": "string"}, "output": {"photo_id": "string"}},
            {"name": "log_survey", "description": "Records one survey entry in the reef log.", "input": {"section_id": "string"}, "output": {"entry_id": "string"}},
        ],
        "mentions": [
            ("Tag the staghorn colonies", "EVENT", "C1", "ACTION"),
            ("the staghorn colonies", "ENTITY", None, "OTHER"),
            ("surveying the reef flat", "EVENT", "C3", "ACTION"),
            ("the reef flat", "ENTITY", None, "OTHER"),
            ("Tag the brain corals", "EVENT", "C2", "ACTION"),
            ("the brain corals", "ENTITY", None, "OTHER"),
            ("the survey", "EVENT_REFERENCE", "C3", "REFERENCE_TO_EVENT"),
            ("Photograph every tagged colony", "EVENT", "C4", "ACTION"),
            ("every tagged colony", "EVENT_REFERENCE", None, "REFERENCE_TO_EVENT"),
        ],
        "normative_edges": [
            ["C1", "C3", ["ORDER_BEFORE"], "Tag the staghorn colonies before surveying the reef flat"],
            ["C3", "C2", ["ORDER_BEFORE", "PRECONDITION"], "Tag the brain corals after the survey"],
        ],
        "related_pairs": [],
        "ambiguous_pairs": [],
        "notes": "same predicate on different objects = two events (hard negative pair, NO related); gerund survey clause is the only mention of the survey; noun reference 'the survey' to a gerund-mentioned action.",
    },
    {
        "case_id": "m_sluice",
        "domain": "dam sluice gate operation",
        "family": "m_verify_embedded_passive_pronoun",
        "policy": "Operate the sluice gate only after it has been inspected. "
                  "Inspect the gate weekly. Verify that the inspection is "
                  "logged.",
        "tools": [
            {"name": "inspect_gate", "description": "Inspects one sluice gate.", "input": {"gate_id": "string"}, "output": {"status": "string"}},
            {"name": "operate_gate", "description": "Operates one sluice gate.", "input": {"gate_id": "string"}, "output": {"status": "string"}},
            {"name": "log_inspection", "description": "Writes one inspection entry into the gate log.", "input": {"gate_id": "string"}, "output": {"entry_id": "string"}},
            {"name": "read_gate_log", "description": "Reads the gate log for one sluice gate.", "input": {"gate_id": "string"}, "output": {"entries": "number"}},
        ],
        "mentions": [
            ("Operate the sluice gate", "EVENT", "S2", "ACTION"),
            ("the sluice gate", "ENTITY", None, "OTHER"),
            ("it has been inspected", "STATE_OR_FACET", "S1", "STATE"),
            ("Inspect the gate", "CHECK", "S1", "CHECK"),
            ("the gate", "ENTITY", None, "OTHER"),
            ("Verify that the inspection is logged", "CHECK", "S4", "CHECK", {"embeds": "the inspection is logged"}),
            ("the inspection is logged", "EVENT", "S3", "RECORD"),
            ("the inspection", "EVENT_REFERENCE", "S1", "REFERENCE_TO_EVENT"),
        ],
        "normative_edges": [
            ["S1", "S2", ["STATE_GATE", "PRECONDITION"], "Operate the sluice gate only after it has been inspected"],
        ],
        "related_pairs": [["S1", "S3"], ["S1", "S4"], ["S3", "S4"]],
        "ambiguous_pairs": [],
        "notes": "pronoun-subject passive facet cross-sentence (it has been inspected -> S1); nested VERIFY over a recording passive; triple nesting verify > record > reference.",
    },
    {
        "case_id": "m_foundry",
        "domain": "foundry melt pouring",
        "family": "m_irregular_morphology_modal_passive",
        "policy": "Sweep the foundry floor before each shift. The floor must "
                  "be swept and the ladles must be preheated. Pour the melt "
                  "only after the floor is swept and the ladles are "
                  "preheated.",
        "tools": [
            {"name": "sweep_floor", "description": "Sweeps one foundry floor.", "input": {"zone_id": "string"}, "output": {"status": "string"}},
            {"name": "preheat_ladle", "description": "Preheats one ladle.", "input": {"ladle_id": "string"}, "output": {"temp_c": "number"}},
            {"name": "pour_melt", "description": "Pours one ladle of melt.", "input": {"ladle_id": "string"}, "output": {"cast_id": "string"}},
            {"name": "log_floor_check", "description": "Records one floor check in the foundry log.", "input": {"zone_id": "string"}, "output": {"entry_id": "string"}},
        ],
        "mentions": [
            ("Sweep the foundry floor", "EVENT", "F1", "ACTION"),
            ("the foundry floor", "ENTITY", None, "OTHER"),
            ("each shift", "ENTITY", None, "OTHER"),
            ("The floor must be swept", "STATE_OR_FACET", "F1", "STATE"),
            ("the floor is swept", "STATE_OR_FACET", "F1", "STATE"),
            ("the ladles must be preheated", "STATE_OR_FACET", "F2", "STATE"),
            ("the ladles are preheated", "STATE_OR_FACET", "F2", "STATE"),
            ("the ladles", "ENTITY", None, "OTHER"),
            ("Pour the melt", "EVENT", "F3", "ACTION"),
            ("the melt", "ENTITY", None, "OTHER"),
        ],
        "normative_edges": [
            ["F1", "F3", ["STATE_GATE", "PRECONDITION"], "Pour the melt only after the floor is swept and the ladles are preheated"],
            ["F2", "F3", ["STATE_GATE", "PRECONDITION"], "Pour the melt only after the floor is swept and the ladles are preheated"],
        ],
        "related_pairs": [],
        "ambiguous_pairs": [],
        "notes": "irregular morphology sweep->swept (imperative, modal passive, result passive all one cid); preheat has no active mention (referenced only via modal/result passives, own cid); coordinated gates.",
    },
]

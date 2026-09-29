"""F6 sealed suite — CF minimal-pair twins + rename maps.

Twin schema (F5-compatible, extended):
  twin_id, mechanism, flip_kind,
  a/b: {policy, focus: [spanA, spanB], expected: identity label}
  Optional: expected_entity (entity-binding flips), expected_gate
  (which mention gates the consequent + its semantic type).

Directive-mandated pairs (section 2) are included verbatim where the
directive gave exact sentences (cf_crate, cf_cleanse, cf_logged); the
remaining twins are new constructions that do not reuse F3/F4/F5
formulations.
"""

F6_CF_TWINS = [
    {
        "twin_id": "cf_crate",
        "mechanism": "entity_id_binding",
        "flip_kind": "entity_id_binding",
        "a": {
            "policy": "Inspect crate 51 before loading crate 51.",
            "focus": ["Inspect crate 51", "loading crate 51"],
            "expected": "DIFFERENT_EVENT",
            "expected_entity": {"pair": ["crate 51", "crate 51"], "label": "SAME_ENTITY"},
            "argument_gold": {"loading": "crate 51", "inspect": "crate 51"},
        },
        "b": {
            "policy": "Inspect crate 51 before loading crate 52.",
            "focus": ["Inspect crate 51", "loading crate 52"],
            "expected": "DIFFERENT_EVENT",
            "expected_entity": {"pair": ["crate 51", "crate 52"], "label": "DIFFERENT_ENTITY"},
            "argument_gold": {"loading": "crate 52", "inspect": "crate 51"},
        },
        "note": "directive example: the numeric object of 'loading' must flip 51->52 while the inspected object stays 51; identity labels are equal on both sides, the flip is in argument/entity binding.",
    },
    {
        "twin_id": "cf_cleanse",
        "mechanism": "action_vs_check_gate",
        "flip_kind": "gate_action_vs_check",
        "a": {
            "policy": "Clean the vessel before filling it.",
            "focus": ["Clean the vessel", "filling it"],
            "expected": "DIFFERENT_EVENT",
            "expected_gate": {"span": "Clean the vessel", "sem": "ACTION"},
        },
        "b": {
            "policy": "Verify that the vessel was cleaned before filling it.",
            "focus": ["Verify that the vessel was cleaned", "the vessel was cleaned"],
            "expected": "RELATED_BUT_DIFFERENT",
            "expected_gate": {"span": "the vessel was cleaned", "sem": "STATE"},
        },
        "note": "directive example: side A gates filling with the ACTION; side B embeds the cleaned state inside a verification - a CHECK mention must appear in B and must NOT be merged with the cleaned state (the F5 check-embedding failure class).",
    },
    {
        "twin_id": "cf_logged",
        "mechanism": "action_vs_recording_of_action",
        "flip_kind": "action_vs_record",
        "a": {
            "policy": "The vessel was cleaned. Notify the shift lead after the cleaning.",
            "focus": ["The vessel was cleaned", "the cleaning"],
            "expected": "SAME_EVENT",
        },
        "b": {
            "policy": "The vessel was cleaned. The cleaning was logged.",
            "focus": ["The vessel was cleaned", "The cleaning was logged"],
            "expected": "RELATED_BUT_DIFFERENT",
        },
        "note": "directive example: recording of an action is a DISTINCT event (H.3 regression class 'The cleaning is logged' from F5).",
    },
    {
        "twin_id": "cf_grind",
        "mechanism": "same_predicate_object_split",
        "flip_kind": "same_predicate_object_split_with_irregular_and_substring",
        "a": {
            "policy": "Grind the coffee beans. Brewing starts after the beans are ground.",
            "focus": ["Grind the coffee beans", "the beans are ground"],
            "expected": "SAME_EVENT",
        },
        "b": {
            "policy": "Grind the coffee beans. Grind the chicory root. The blend lists both grinds.",
            "focus": ["Grind the coffee beans", "Grind the chicory root"],
            "expected": "DIFFERENT_EVENT",
        },
        "note": "irregular passive grind->ground on side A; same predicate on different objects on side B; 'grinds' (plural noun) is a substring-lemma trap distinct from the verb.",
    },
    {
        "twin_id": "cf_gatecheck",
        "mechanism": "gate_action_vs_check_of_state",
        "flip_kind": "gate_action_vs_check_of_state",
        "a": {
            "policy": "Fill the tank before starting the pump.",
            "focus": ["Fill the tank", "starting the pump"],
            "expected": "DIFFERENT_EVENT",
            "expected_gate": {"span": "Fill the tank", "sem": "ACTION"},
        },
        "b": {
            "policy": "Check that the tank is full before starting the pump.",
            "focus": ["Check that the tank is full", "the tank is full"],
            "expected": "RELATED_BUT_DIFFERENT",
            "expected_gate": {"span": "the tank is full", "sem": "STATE"},
        },
        "note": "directive class 'check of a state vs execution of the action producing that state': side A gates with an action, side B with a check over a state (no fill action exists at all in B).",
    },
    {
        "twin_id": "cf_replace",
        "mechanism": "prescribed_vs_performed_occurrence",
        "flip_kind": "prescribed_vs_performed",
        "a": {
            "policy": "Replace the filter. The filter was replaced last week.",
            "focus": ["Replace the filter", "The filter was replaced"],
            "expected": "DIFFERENT_EVENT",
        },
        "b": {
            "policy": "Replace the filter. The filter is replaced every quarter.",
            "focus": ["Replace the filter", "The filter is replaced"],
            "expected": "SAME_EVENT",
        },
        "note": "directive class 'action completed vs action requested': the standing rule and a reported PAST occurrence are different events; the standing rule and its habitual passive restatement are the same event.",
    },
]

# ---------------------------------------------------------------- renames
# 6 representative cases, entity nouns renamed (structure preserved).
# Applied programmatically to policy + mention spans + edge evidence.
F6_RENAMES = {
    "m_sluice": {
        "case_id_new": "m_sluice_ren",
        "map": [
            ["sluice gate", "penstock valve"],
            ["the gate", "the valve"],
            ["gate log", "valve log"],
            ["Inspect the gate", "Inspect the valve"],
        ],
        "tool_map": [
            ["inspect_gate", "inspect_valve"],
            ["operate_gate", "operate_valve"],
            ["log_inspection", "log_valve_inspection"],
            ["read_gate_log", "read_valve_log"],
            ["sluice gate", "penstock valve"],
        ],
    },
    "m_mint": {
        "case_id_new": "m_mint_ren",
        "map": [
            ["coin blanks", "medal discs"],
            ["the coins", "the medals"],
        ],
        "tool_map": [
            ["weigh_blanks", "weigh_discs"],
            ["anneal_blanks", "anneal_discs"],
            ["strike_coins", "strike_medals"],
            ["log_blank_weight", "log_disc_weight"],
            ["coin blanks", "medal discs"],
        ],
    },
    "m_coral": {
        "case_id_new": "m_coral_ren",
        "map": [
            ["staghorn colonies", "gorgonian fans"],
            ["brain corals", "mound corals"],
            ["reef flat", "lagoon shelf"],
        ],
        "tool_map": [],
    },
    "l_roastery": {
        "case_id_new": "l_roastery_ren",
        "map": [
            ["beans", "granules"],
            ["roast sheet", "roast ledger"],
            ["the roaster", "the operator"],
        ],
        "tool_map": [
            ["roast_beans", "roast_granules"],
            ["file_roast_sheet", "file_roast_ledger"],
        ],
    },
    "s_fishery": {
        "case_id_new": "s_fishery_ren",
        "map": [
            ["fish 44", "seal 12"],
            ["fish 45", "seal 13"],
        ],
        "tool_map": [
            ["weigh_fish", "weigh_seal"],
            ["tag_fish", "tag_seal"],
            ["record_weight", "record_seal_weight"],
        ],
    },
    "s_incubator": {
        "case_id_new": "s_incubator_ren",
        "map": [
            ["incubator", "proofing cabinet"],
            ["samples", "trays"],
        ],
        "tool_map": [
            ["warm_incubator", "warm_cabinet"],
            ["load_samples", "load_trays"],
            ["check_incubator_temp", "check_cabinet_temp"],
            ["log_temperature", "log_cabinet_temp"],
            ["incubator log", "cabinet log"],
        ],
    },
}

from guardian_truth.cycle2.failure_audit import _failure_type, _x5_components


def test_binary_failure_taxonomy():
    assert _failure_type(1, 0) == "FALSE_NEGATIVE"
    assert _failure_type(0, 1) == "FALSE_POSITIVE"
    assert _failure_type(1, 1) is None


def test_x5_upstream_unknowns_are_nonexclusive():
    row = {"telemetry": {
        "n_policy_rules": 0,
        "n_unknown_policy_segments": 1,
        "n_claims": 1,
        "n_unknown_claim_spans": 2,
        "n_unknown_tools": 3,
        "n_candidate_bindings": 0,
        "solver_status": "UNRESOLVED",
    }}
    assert _x5_components(row) == [
        "POLICY_SEMANTICS", "CLAIM_EXTRACTION", "TOOL_EFFECTS", "BINDING",
    ]

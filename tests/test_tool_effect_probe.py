"""Meaningful gates for the experimental tool-effect component."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/searh_23"))

import tool_effect_probe as probe  # noqa: E402


def test_paired_result_outcomes_with_oracle_tool_effect():
    rows = probe.read_rows(ROOT / "experiments/searh_23/tool_effect_v1/dev.jsonl")
    family = [row for row in rows if row["id"].startswith("device_swap__")]
    relations = {"execute_replacement": {"relation": "DIRECT"},
                 "check_authorization": {"relation": "NON_ENTAILING"},
                 "record_audit": {"relation": "NON_ENTAILING"}}
    verdicts = {row["id"].split("__")[1]: probe.evaluate(row, relations)["verdict"]
                for row in family}
    assert verdicts == {
        "supported": "REFUTED_BY_RESULT",
        "related_result": "UNSUPPORTED_COMPLETION_CANDIDATE",
        "audit_result": "UNSUPPORTED_COMPLETION_CANDIDATE",
        "failed_result": "UNSUPPORTED_COMPLETION_CANDIDATE",
        "wrong_entity": "UNSUPPORTED_COMPLETION_CANDIDATE",
        "no_result": "UNSUPPORTED_COMPLETION_CANDIDATE",
    }


def test_ambiguous_and_wrong_effects_are_visible():
    case = probe.read_rows(ROOT / "experiments/searh_23/tool_effect_v1/dev.jsonl")[0]
    ambiguous = {"execute_replacement": {"relation": "DIRECT"},
                 "check_authorization": {"relation": "UNKNOWN"},
                 "record_audit": {"relation": "NON_ENTAILING"}}
    assert probe.evaluate(case, ambiguous)["verdict"] == "UNKNOWN"
    wrong = {"execute_replacement": {"relation": "NON_ENTAILING"},
             "check_authorization": {"relation": "NON_ENTAILING"},
             "record_audit": {"relation": "DIRECT"}}
    result = probe.evaluate(case, wrong)
    assert result["selected_tool"] == "record_audit"
    assert result["verdict"] == "UNSUPPORTED_COMPLETION_CANDIDATE"
    # The second verdict looks right only by accident. Tool mapping must be
    # scored separately from the absence/presence of a result.


def test_request_is_independent_of_observed_results():
    rows = probe.read_rows(ROOT / "experiments/searh_23/tool_effect_v1/dev.jsonl")
    family = [row for row in rows if row["id"].startswith("device_swap__")]
    requests = {probe.request(probe.claim_text(row),
                              probe.source.declared_tool_lines(row)["record_audit"])[1]
                for row in family}
    assert len(requests) == 1

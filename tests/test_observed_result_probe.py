"""Pairing and entity gates for the observed-result component."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/searh_23"))

import observed_result_probe as probe  # noqa: E402


def test_observed_result_controls():
    rows = probe.common.read_rows(ROOT / "experiments/searh_23/tool_effect_v1/fresh.jsonl")
    family = {row["id"].split("__")[1]: row for row in rows
              if row["id"].startswith("parcel_dispatch__")}
    assert probe.observed_pair(family["supported"])[1] is None
    assert probe.observed_pair(family["related_result"])[1] is None
    assert probe.observed_pair(family["audit_result"])[1] is None
    assert probe.classify(family["supported"], {"relation": "ENTAILS"})["verdict"] == \
        "SUPPORTED_BY_RESULT"
    assert probe.classify(family["related_result"],
                          {"relation": "DOES_NOT_ENTAIL"})["verdict"] == \
        "NOT_SUPPORTED_BY_THIS_RESULT"
    for variant in ("failed_result", "wrong_entity"):
        assert probe.classify(family[variant], {"relation": "ENTAILS"})["verdict"] == \
            "NOT_SUPPORTED_BY_THIS_RESULT"
    assert probe.classify(family["no_result"], {"relation": "ENTAILS"})["verdict"] == \
        "UNKNOWN"

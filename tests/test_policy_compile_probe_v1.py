"""Source coverage cannot silently turn an omitted clause into SAFE."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/searh_23"))

from build_policy_language_v1 import POLICIES  # noqa: E402
from micrograph_certificate_v1 import _bullets, compile_policy  # noqa: E402
from policy_compile_probe_v1 import source_gated_verdict, validate_translation  # noqa: E402


PRE = ("Before replacing any device, check that the warranty is active for the SAME case. "
       "A check for a different case does not satisfy this condition.")
LATEST = ("Use the latest warranty-check result for that case. "
          "An earlier active result cannot override a later inactive result.")
AFTER = ("After a device has been replaced successfully, record a service audit "
         "for the SAME case. Do not record the audit before successful replacement.")


def test_complete_normalization_is_compilable() -> None:
    bullets = _bullets(POLICIES["until_latest"])
    answer = {"entries": [
        {"source_id": 0, "source_quote": bullets[0],
         "canonical_bullets": [PRE, LATEST], "unsupported": False},
        {"source_id": 1, "source_quote": bullets[1],
         "canonical_bullets": [AFTER], "unsupported": False},
    ]}
    policy, errors = validate_translation(bullets, answer)
    assert errors == []
    assert compile_policy(policy)[1] == []


def test_omitted_supervisor_entry_fails_coverage() -> None:
    bullets = _bullets(POLICIES["extra_supervisor"])
    answer = {"entries": [
        {"source_id": 0, "source_quote": bullets[0],
         "canonical_bullets": [PRE, LATEST], "unsupported": False},
        {"source_id": 2, "source_quote": bullets[2],
         "canonical_bullets": [AFTER], "unsupported": False},
    ]}
    policy, errors = validate_translation(bullets, answer)
    assert not policy
    assert errors == ["source_coverage_failed"]


def test_dropped_supervisor_constraint_stays_unsupported() -> None:
    bullets = _bullets(POLICIES["extra_supervisor"])
    answer = {"entries": [
        {"source_id": 0, "source_quote": bullets[0],
         "canonical_bullets": [PRE, LATEST], "unsupported": False},
        {"source_id": 1, "source_quote": bullets[1],
         "canonical_bullets": [PRE], "unsupported": False},
        {"source_id": 2, "source_quote": bullets[2],
         "canonical_bullets": [AFTER], "unsupported": False},
    ]}
    policy, errors = validate_translation(bullets, answer)
    assert any(error.startswith("critical_constraint_dropped:1") for error in errors)
    assert "supervisor" in policy
    assert compile_policy(policy)[1]


def test_dropped_newest_condition_stays_unsupported() -> None:
    bullets = _bullets(POLICIES["permission"])
    answer = {"entries": [
        {"source_id": 0, "source_quote": bullets[0],
         "canonical_bullets": [PRE], "unsupported": False},
        {"source_id": 1, "source_quote": bullets[1],
         "canonical_bullets": [AFTER], "unsupported": False},
    ]}
    policy, errors = validate_translation(bullets, answer)
    assert errors == ["latest_condition_dropped:0"]
    assert compile_policy(policy)[1]


def test_model_can_drop_unlisted_requirement_so_paraphrase_cannot_certify_safe() -> None:
    original = ("# Repair desk policy\n- Before replacing any device, check that the warranty "
                "is active for the SAME case and the defective device has already been returned.")
    canonical = "# Repair desk policy\n- " + PRE + "\n- " + LATEST
    candidate = {"verdict": "SAFE", "coverage": "COMPLETE_BOUNDED_GRAMMAR"}
    assert source_gated_verdict(original, canonical, [], candidate) == "UNKNOWN"

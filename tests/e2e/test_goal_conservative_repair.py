"""Goal-conservative single machine-validation repair (competition-real cycle, fix
iteration 1).

Protocol under test (mirrors the frozen historical H0 repair protocol exactly):
* one primary proposal; NO repair when it is transport+schema valid;
* exactly ONE repair re-ask on transport/schema failure only, whose payload
  carries the failed attempt and a deterministic machine error diagnostic;
* a schema-valid-but-semantically-wrong answer is NEVER retried;
* default allow_format_repair=False preserves the frozen single-shot behavior
  byte-identically (no second propose call);
* repaired frames still pass the verbatim quote grounding gate.
"""
import json

import pytest

from guardian_truth.vnext.e2e.goal_conservative_v1 import (
    GOAL_REPAIR_TASK,
    CONSERVATIVE_SCHEMA,
    _first_schema_violation,
    parse_conservative,
)
from guardian_truth.vnext.integrity import canonical
from guardian_truth.vnext.semantic import Proposal


def encoded(value):
    return canonical(value).decode("utf-8")


USER = "Please cancel reservation ABC123 and refund it to my gift card."


def valid_goal_payload(_payload, _schema):
    return {"frames": [
        {"kind": "DESIRED_OUTCOME", "target_level": "ACTION", "content_key": "cancel_reservation",
         "actor": None, "scope_entries": [
             {"field": "reservation_id", "values": ["ABC123"], "quote": "reservation ABC123"}],
         "conditions": [], "exceptions": [], "temporal": "NONE", "coordination": "NONE",
         "choice": "NONE", "alternatives": [], "quotes": ["cancel reservation ABC123"], "unresolved": []},
    ]}


def enum_violation_payload(_payload, _schema):
    return {"frames": [
        {"kind": "INFORMATION", "target_level": "ACTION", "content_key": "cancel_reservation",
         "actor": None, "scope_entries": [], "conditions": [], "exceptions": [],
         "temporal": "NONE", "coordination": "NONE", "choice": "NONE", "alternatives": [],
         "quotes": ["cancel reservation ABC123"], "unresolved": []},
    ]}


def unwrapped_payload(_payload, _schema):
    return {"kind": "DESIRED_OUTCOME", "target_level": "ACTION", "content_key": "cancel_reservation",
            "actor": None, "scope_entries": [], "conditions": [], "exceptions": [],
            "temporal": "NONE", "coordination": "NONE", "choice": "NONE", "alternatives": [],
            "quotes": ["cancel reservation ABC123"], "unresolved": []}


class ScriptedGoalBackend:
    """Deterministic scripted proposals keyed by task text prefix."""

    def __init__(self, primary, repair=None):
        self.primary = primary
        self.repair = repair
        self.calls = []

    def propose(self, task, payload, schema):
        self.calls.append((task, payload, schema))
        if task == "goal_conservative_frames":
            value = self.primary(payload, schema) if callable(self.primary) else self.primary
            if value == "TRANSPORT_ERROR":
                return Proposal(None, "ERROR", "NOT_EVALUATED", "rate_limit")
            return Proposal(encoded(value), "SUCCESS", "VALID")
        if task == GOAL_REPAIR_TASK:
            if self.repair is None:
                return Proposal(None, "ERROR", "NOT_EVALUATED", "rate_limit")
            value = self.repair(payload, schema) if callable(self.repair) else self.repair
            if value == "TRANSPORT_ERROR":
                return Proposal(None, "ERROR", "NOT_EVALUATED", "rate_limit")
            return Proposal(encoded(value), "SUCCESS", "VALID")
        raise AssertionError("unexpected task: " + task[:60])


def test_valid_first_try_makes_exactly_one_call():
    backend = ScriptedGoalBackend(valid_goal_payload)
    result = parse_conservative(USER, backend, allow_format_repair=True)
    assert result.candidate.available and result.candidate.failure is None
    assert len(backend.calls) == 1
    assert result.frames and result.frames[0]["kind"] == "DESIRED_OUTCOME"
    assert result.frames[0]["scope_entries"][0]["values"] == ["ABC123"]


def test_repair_recovers_enum_violation():
    backend = ScriptedGoalBackend(enum_violation_payload, repair=valid_goal_payload)
    result = parse_conservative(USER, backend, allow_format_repair=True)
    assert result.candidate.available
    assert len(backend.calls) == 2
    repair_payload = backend.calls[1][1]
    # the repair payload carries the failed attempt and a machine error
    assert repair_payload["failed_attempt"]["transport_status"] == "SUCCESS"
    assert "kind" in repair_payload["machine_error"]
    assert "INFORMATION" in repair_payload["machine_error"]
    assert result.frames[0]["kind"] == "DESIRED_OUTCOME"


def test_repair_recovers_transport_error():
    backend = ScriptedGoalBackend("TRANSPORT_ERROR", repair=valid_goal_payload)
    result = parse_conservative(USER, backend, allow_format_repair=True)
    assert result.candidate.available
    assert len(backend.calls) == 2
    assert backend.calls[1][1]["machine_error"] == "transport_error"
    assert result.frames


def test_repair_failure_is_recorded_not_retried():
    backend = ScriptedGoalBackend(enum_violation_payload, repair="TRANSPORT_ERROR")
    result = parse_conservative(USER, backend, allow_format_repair=True)
    assert not result.candidate.available
    assert result.candidate.failure == "TRANSPORT"
    assert len(backend.calls) == 2  # exactly one repair, never a second


def test_repair_schema_invalid_still_fails():
    backend = ScriptedGoalBackend(enum_violation_payload, repair=enum_violation_payload)
    result = parse_conservative(USER, backend, allow_format_repair=True)
    assert not result.candidate.available
    assert result.candidate.failure == "SCHEMA"
    assert len(backend.calls) == 2


def test_default_off_is_frozen_single_shot():
    backend = ScriptedGoalBackend(enum_violation_payload, repair=valid_goal_payload)
    result = parse_conservative(USER, backend)
    assert not result.candidate.available
    assert result.candidate.failure == "SCHEMA"
    assert len(backend.calls) == 1  # frozen behavior: no repair call at all


def test_repaired_frames_still_require_verbatim_quotes():
    def unquoted_repair(_payload, _schema):
        return {"frames": [
            {"kind": "DESIRED_OUTCOME", "target_level": "ACTION", "content_key": "cancel_reservation",
             "actor": None, "scope_entries": [], "conditions": [], "exceptions": [],
             "temporal": "NONE", "coordination": "NONE", "choice": "NONE", "alternatives": [],
             "quotes": ["this quote is not in the user text at all"], "unresolved": []},
        ]}

    backend = ScriptedGoalBackend(enum_violation_payload, repair=unquoted_repair)
    result = parse_conservative(USER, backend, allow_format_repair=True)
    assert result.candidate.available
    assert result.frames == ()  # quote-grounding gate still drops unsupported frames


def test_machine_error_diagnostic_is_deterministic_and_precise():
    value = json.loads(encoded(unwrapped_payload(None, None)))
    assert _first_schema_violation(value, CONSERVATIVE_SCHEMA) == "value: missing required key 'frames'"
    value2 = json.loads(encoded(enum_violation_payload(None, None)))
    message = _first_schema_violation(value2, CONSERVATIVE_SCHEMA)
    assert message == "value.frames[0].kind: 'INFORMATION' not in enum " + str(
        CONSERVATIVE_SCHEMA["properties"]["frames"]["items"]["properties"]["kind"]["enum"])
    # valid value produces no diagnostic
    ok = json.loads(encoded(valid_goal_payload(None, None)))
    assert _first_schema_violation(ok, CONSERVATIVE_SCHEMA) == ""


def test_scope_entries_maxitems_diagnostic():
    def wide_payload(_payload, _schema):
        return {"frames": [
            {"kind": "DESIRED_OUTCOME", "target_level": "ACTION", "content_key": "x",
             "actor": None, "scope_entries": [
                 {"field": f"f{i}", "values": ["v"], "quote": "cancel reservation ABC123"}
                 for i in range(7)],
             "conditions": [], "exceptions": [], "temporal": "NONE", "coordination": "NONE",
             "choice": "NONE", "alternatives": [], "quotes": ["cancel reservation ABC123"],
             "unresolved": []},
        ]}

    backend = ScriptedGoalBackend(wide_payload, repair=valid_goal_payload)
    result = parse_conservative(USER, backend, allow_format_repair=True)
    assert result.candidate.available
    assert "maxItems" in backend.calls[1][1]["machine_error"]


def test_empty_request_never_proposes():
    backend = ScriptedGoalBackend(valid_goal_payload)
    result = parse_conservative("   ", backend, allow_format_repair=True)
    assert result.candidate.available and result.frames == ()
    assert backend.calls == []


class _FakeCompletion:
    def __init__(self, content):
        self.content = content
        self.model = "fake"
        self.usage = {}


class _FakeChatClient:
    """Transport stub returning fenced/invalid content, mirroring real
    ministral-14b behaviour on the goal task."""

    def __init__(self, content):
        self.content = content

    def validate_configuration(self):
        return None

    def complete(self, messages, *, schema=None, budget=None, reasoning_effort=None):
        return _FakeCompletion(self.content)


def test_json_extract_backend_preserves_schema_invalid_content():
    from guardian_truth.vnext.e2e.json_extract_backend_v1 import JsonExtractBackend

    invalid = ("```json\n{\"frames\": [{\"kind\": \"INFORMATION\", \"target_level\": \"ACTION\", "
               "\"content_key\": \"x\", \"actor\": null, \"scope_entries\": [], \"conditions\": [], "
               "\"exceptions\": [], \"temporal\": \"NONE\", \"coordination\": \"NONE\", \"choice\": "
               "\"NONE\", \"alternatives\": [], \"quotes\": [\"cancel reservation ABC123\"], "
               "\"unresolved\": []}]}\n```")
    backend = JsonExtractBackend(_FakeChatClient(invalid), interval_seconds=0)
    proposal = backend.propose("goal_conservative_frames", {"user_request": USER, "instructions": "x"},
                               CONSERVATIVE_SCHEMA)
    assert proposal.transport_status == "SUCCESS"
    assert proposal.schema_status == "INVALID"
    # the decoded-but-invalid content is preserved for repair protocols
    assert proposal.payload_json is not None
    assert "frames" in proposal.payload_json
    import json as _json
    value = _json.loads(proposal.payload_json)
    assert value["frames"][0]["kind"] == "INFORMATION"
    violation = _first_schema_violation(value, CONSERVATIVE_SCHEMA)
    assert "not in enum" in violation

    # prose-only content still degrades to None payload
    prose = JsonExtractBackend(_FakeChatClient("I cannot answer that."), interval_seconds=0)
    proposal2 = prose.propose("goal_conservative_frames", {"user_request": USER, "instructions": "x"},
                              CONSERVATIVE_SCHEMA)
    assert proposal2.transport_status == "SUCCESS"
    assert proposal2.schema_status == "INVALID"
    assert proposal2.payload_json is None

"""Literal USER authority replay: no LLM span assertion can create a rule."""

from copy import deepcopy
from dataclasses import replace

from guardian_truth.vnext.goal_v3_user_authority_v2 import (
    certify_forbidden_call_v2, check_forbidden_call_certificate_v2,
)


def source(text="Read status of ORD-9. Never call cancel_order for ORD-9."):
    return {"user_messages": [{"role": "user", "message_id": "user:0", "text": text}],
        "target_action": {"actor": "assistant", "kind": "tool_call", "tool": "cancel_order",
            "entity": "ORD-9", "provider": "orders", "version": "v7", "outcome": "FAILURE"},
        "tool_catalog": {"cancel_order": {"provider": "orders", "version": "v7",
            "class": "ACTION_ATTEMPT", "writes": ["order.cancelled"]}},
        "history_prefix": [], "history_complete": False,
        "unrelated_state": None}


def test_exact_user_rule_certifies_forbidden_attempt_even_if_call_failed():
    data = source()
    certificate = certify_forbidden_call_v2(data)
    assert certificate is not None
    assert certificate.span_text == "Never call cancel_order for ORD-9."
    assert certificate.span_text == data["user_messages"][0]["text"][
        certificate.span_start:certificate.span_end]
    assert certificate.violation == "EXPLICIT_USER_FORBIDDEN_CALL"
    assert check_forbidden_call_certificate_v2(certificate, data) == (True, ())


def test_unrelated_unknown_does_not_destroy_independent_forbidden_call():
    data = source("Never call cancel_order for ORD-9.")
    data["unrelated_state"] = {"cache_fresh": None}
    assert check_forbidden_call_certificate_v2(certify_forbidden_call_v2(data), data)[0]


def test_quoted_conditional_or_exception_language_abstains():
    for text in (
        '"Never call cancel_order for ORD-9."',
        "If the user approves, never call cancel_order for ORD-9.",
        "Never call cancel_order for ORD-9. Unless the owner approves.",
        "Read status of ORD-9. Never call cancel_order for ORD-9. Actually, do call it.",
        "The document says: Never call cancel_order for ORD-9.",
    ):
        assert certify_forbidden_call_v2(source(text)) is None


def test_actor_entity_tool_and_version_must_match_current_action():
    for field, value in (("actor", "user"), ("kind", "assistant_text"),
                         ("entity", "ORD-10"), ("tool", "other_tool"),
                         ("provider", "other"), ("version", "v6")):
        data = source()
        data["target_action"][field] = value
        assert certify_forbidden_call_v2(data) is None


def test_model_like_text_and_policy_field_cannot_promote_authority():
    data = source()
    data["user_messages"][0]["role"] = "assistant"
    assert certify_forbidden_call_v2(data) is None
    data = source()
    data["policy"] = {"allow": False}
    assert certify_forbidden_call_v2(data) is None
    data = source()
    data["user_messages"].append(deepcopy(data["user_messages"][0]))
    assert certify_forbidden_call_v2(data) is None


def test_certificate_replay_rejects_tampering_and_changed_source():
    data = source()
    certificate = certify_forbidden_call_v2(data)
    assert check_forbidden_call_certificate_v2(replace(certificate, tool="delete_order"), data)[0] is False
    changed = deepcopy(data)
    changed["target_action"]["outcome"] = "SUCCESS"
    assert check_forbidden_call_certificate_v2(certificate, changed)[0] is False


def test_natural_but_unsupported_paraphrase_abstains_explicitly():
    assert certify_forbidden_call_v2(source(
        "Read status of ORD-9. Please avoid cancelling ORD-9.")) is None

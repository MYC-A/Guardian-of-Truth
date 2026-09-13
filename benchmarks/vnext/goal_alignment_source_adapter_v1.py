"""Project controlled Goal v3 source premises without leaking reference labels.

This is benchmark infrastructure, not the v3 semantic frontend or a verdict
oracle. The explicit fixture is authoritative only inside this controlled suite.
"""

from copy import deepcopy

from guardian_truth.vnext.integrity import digest


SOURCE_CASE_KEYS = frozenset({
    "user", "assistant_plan", "target_patch", "history", "history_complete",
    "session_complete", "obligations", "unrelated_goal_term",
})
NON_SOURCE_KEYS = frozenset({"id", "family", "reference", "meaning_universe"})


def _expand_event(value, templates, seen=()):
    if isinstance(value, str):
        value = {"extends": value}
    if not isinstance(value, dict):
        raise ValueError("source event must be an object or a known template name")
    parent = value.get("extends")
    if parent is None:
        return deepcopy(value)
    if parent not in templates or parent in seen:
        raise ValueError("unknown or cyclic source event template")
    expanded = _expand_event(templates[parent], templates, (*seen, parent))
    expanded.update(deepcopy({key: item for key, item in value.items() if key != "extends"}))
    return expanded


def project_goal_alignment_source(spec, case):
    """Return only source-owned facts; never inspect expected outcomes.

    Case metadata is accepted for compatibility with the frozen spec but omitted
    byte-for-byte from the projection. Unknown keys fail closed so a new gold or
    annotation field cannot silently reach an LLM request.
    """
    if not isinstance(spec, dict) or not isinstance(case, dict):
        raise ValueError("fixture specification and case objects required")
    unknown = set(case) - SOURCE_CASE_KEYS - NON_SOURCE_KEYS
    if unknown:
        raise ValueError("unknown case fields cannot enter source projection")
    fixture = spec["fixture"]
    templates = spec["event_templates"]
    obligations = spec["obligation_templates"]
    selected = case.get("obligations", ())
    if not isinstance(selected, (list, tuple)) or len(selected) != len(set(selected)):
        raise ValueError("unique selected source obligations required")
    if set(selected) - set(obligations):
        raise ValueError("selected obligation has no source text")
    target = deepcopy(fixture["default_target"])
    target.update(deepcopy(case.get("target_patch", {})))
    raw_history = case.get("history", fixture["default_history"])
    if not isinstance(raw_history, list):
        raise ValueError("source history must be a list")
    history = [{"event_id": f"source-event:{index:04d}", "ordinal": index,
                "source": _expand_event(event, templates)}
               for index, event in enumerate(raw_history)]
    history_complete = case.get("history_complete", fixture["default_history_complete"])
    session_complete = case.get("session_complete", fixture["default_session_complete"])
    if type(history_complete) is not bool or type(session_complete) is not bool:
        raise ValueError("source completeness and session boundary require booleans")
    open_permission = "open_permission" in selected
    if open_permission and len(selected) != 1:
        raise ValueError("replacement permission source cannot combine with old obligations")
    system = [] if open_permission else [{"role": "system", "text": fixture["system"], "source_id": "fixture:system:0"}]
    system.extend({"role": "system", "text": obligations[name],
                   "source_id": f"fixture:system:obligation:{ordinal}"}
                  for ordinal, name in enumerate(selected))
    source = {
        "user_messages": [{"role": "user", "text": case.get("user", fixture["user"]),
                           "source_id": "fixture:user:0"}],
        "system_messages": system,
        "capability_contract": {
            "version": fixture["capability_contract_version"],
            "explicit_fixture_catalog_not_real_provider_schema": deepcopy(fixture["capabilities"]),
            "authorization_universe_closed_by_system": not open_permission,
        },
        "assistant_plan": deepcopy(case.get("assistant_plan", [])),
        "target_action": target,
        "history_prefix": history,
        "history_complete": history_complete,
        "history_completeness_basis": "explicit fixture complete prefix" if history_complete else None,
        "session_complete": session_complete,
        "unrelated_goal_term": case.get("unrelated_goal_term"),
        "source_scope": "CONTROLLED_EXPLICIT_FIXTURE_PREMISES_NOT_REAL_WORLD_AUTHORITY",
    }
    return {"schema_version": "guardian-goal-v3-source-projection-v1",
            "source_sha256": digest(source), "source": source}

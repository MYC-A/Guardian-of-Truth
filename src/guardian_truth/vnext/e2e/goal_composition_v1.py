"""Goal composition: Conservative and Rule Frames frontends lower into the
same canonical Goal semantics and then into the shared CompiledRule program
space (spec 57-82). Firewall: PASS 1 sees only the user request.

Frame -> rule compilation:
  DESIRED_OUTCOME / AUTHORIZATION (single)  -> GOAL_CALL (scope expansion
      violates; authorization is NOT a requirement to execute all tools).
  AUTHORIZATION with alternatives (ANY_OF)  -> GOAL_ALTERNATIVES (OR over
      allowed alternatives per call).
  PROHIBITION                              -> FORBID_CALL, or REQUIRE_PRESERVE
      when the frame targets a state-contract field.
  OBLIGATION                               -> REQUIRE_CALL (BEFORE anchor ->
      FORBID_CALL with prerequisite condition).
  GUARD                                    -> unresolved marker in V1 unless
      already represented as a per-frame condition by the frontend.
  UNKNOWN                                  -> unresolved marker.
"""

from __future__ import annotations

import re

from ..integrity import canonical, digest
from .e2e_types_v1 import (CompiledCondition, CompiledRule, ExtractiveRef, GoalContract, GoalFrame, ScopeEntry)
from .policy_composition_v1 import _key_from, _quote_value_forms

GOAL_COMPOSITION_VERSION = "goal_composition_e2e_v1"


def _goal_rule(index, kind, modality, action_key, conditions, exceptions, scope, quotes,
               unresolved, alternatives=()):
    return CompiledRule(
        rule_id=f"goal:rule{index}", kind=kind, modality=modality, action_key=action_key,
        actor="assistant", relation="NONE", conditions=tuple(conditions), exceptions=tuple(exceptions),
        scope=tuple(scope), source_quotes=tuple(quotes), unresolved_terms=tuple(unresolved),
        frontend="goal", alternatives=tuple(alternatives))


def _value_forms(values) -> tuple[str, ...]:
    forms = []
    for value in values:
        raw = str(value)
        forms.extend(_quote_value_forms(raw))
    return tuple(dict.fromkeys(forms))


def compile_goal_contract(contract: GoalContract, state_contract: dict | None):
    """GoalContract -> (rules, unresolved_terms). Deterministic, no LLM."""
    state = state_contract or {}
    rules, unresolved = [], list(contract.unresolved_terms)
    for i, frame in enumerate(contract.frames):
        quotes = tuple(dict.fromkeys(ref.quote for ref in frame.support))
        key = frame.content_key or _key_from(quotes[0] if quotes else "", None)
        # SND-10 (pre-benchmark audit): CompiledCondition requires the
        # 'bound' argument; the previous call omitted it and ANY goal frame
        # carrying conditions/exceptions crashed compile_goal_contract.
        conditions = tuple(CompiledCondition(_key_from(c, c), False, "HISTORY",
                                             quotes[0] if quotes else c)
                           for c in frame.conditions)
        exceptions = tuple(CompiledCondition(_key_from(e, e), True, "HISTORY",
                                             quotes[0] if quotes else e)
                           for e in frame.exceptions)
        scope = tuple((entry.field, _value_forms(entry.values)) for entry in frame.scope)
        frame_unresolved = list(frame.unresolved_fields)
        kind = frame.frame_kind
        if kind == "UNKNOWN":
            unresolved.append(f"goal:frame kind unknown ({key})")
            continue
        if frame.temporal in {"BEFORE", "AFTER"} and kind in {"OBLIGATION", "DESIRED_OUTCOME"}:
            # Explicit ordering semantics: anchor must precede the action.
            anchor = conditions[0] if conditions else None
            if anchor is not None and kind == "OBLIGATION":
                rules.append(_goal_rule(i, "FORBID_CALL", "REQUIRE", key, (anchor,), exceptions,
                                        scope, quotes, frame_unresolved))
                continue
            frame_unresolved.append("temporal relation not expressible for this frame kind")
        if kind == "DESIRED_OUTCOME" or kind == "AUTHORIZATION":
            alternatives = tuple(dict.fromkeys(frame_alternatives(frame)))
            if len(alternatives) > 1:
                if frame.choice == "EXACTLY_ONE":
                    # Exactly-one among several alternatives is a real choice
                    # cardinality the V1 program space cannot express.
                    unresolved.append("goal:exactly-one choice cardinality not expressible in V1")
                else:
                    rules.append(_goal_rule(i, "GOAL_ALTERNATIVES", "PERMIT" if kind == "AUTHORIZATION" else "REQUIRE",
                                            key, conditions, exceptions, scope, quotes, frame_unresolved,
                                            alternatives=alternatives))
                continue
            # A single alternative with EXACTLY_ONE is simply that action.
            rules.append(_goal_rule(i, "GOAL_CALL", "REQUIRE", key, conditions, exceptions, scope,
                                    quotes, tuple(term for term in frame_unresolved if term != "actor")))
            continue
        if kind == "PROHIBITION":
            field_hit = None
            hay = " ".join(quotes) + " " + (frame.content_key or "").replace("_", " ")
            for field_name in sorted(state):
                if re.search(r"(?<![\w])" + re.escape(field_name) + r"(?![\w])", hay):
                    field_hit = field_name
                    break
            if field_hit is not None:
                rules.append(_goal_rule(i, "REQUIRE_PRESERVE", "FORBID", key, conditions, exceptions,
                                        ((field_hit, tuple(canonical(v).decode("utf-8") for v in state[field_hit])),),
                                        quotes, frame_unresolved))
            elif frame.scope:
                rules.append(_goal_rule(i, "FORBID_CALL", "FORBID", key, conditions, exceptions,
                                        scope, quotes, frame_unresolved))
            else:
                rules.append(_goal_rule(i, "FORBID_CALL", "FORBID", key, conditions, exceptions, (),
                                        quotes, frame_unresolved))
            continue
        if kind == "OBLIGATION":
            rules.append(_goal_rule(i, "REQUIRE_CALL", "REQUIRE", key, conditions, exceptions, scope,
                                    quotes, frame_unresolved))
            continue
        if kind == "GUARD":
            unresolved.append(f"goal:guard applicability unknown ({key})")
            continue
        unresolved.append(f"goal:frame not compilable ({key})")
    return tuple(rules), tuple(dict.fromkeys(unresolved))


def frame_alternatives(frame: GoalFrame) -> tuple[str, ...]:
    """Alternative action keys explicitly authorized by the user."""
    return tuple(frame.alternatives or ())


def conservative_frames_to_contract(frames: tuple[dict, ...], unresolved_terms: tuple[str, ...]) -> GoalContract:
    """Conservative frames (dict form) -> GoalContract with canonical frames."""
    canonical_frames = []
    for item in frames:
        support = tuple(dict.fromkeys(item["quotes"]))
        scope = tuple(ScopeEntry(entry["field"], tuple(entry["values"]), None)
                      for entry in item["scope_entries"])
        frame = GoalFrame(
            frame_kind=item["kind"], target_level=item["target_level"],
            actor=None if item["actor"] in {"UNKNOWN", ""} else item["actor"],
            content_key=item["content_key"], entity_key=None,
            scope=scope, conditions=tuple(item["conditions"]), exceptions=tuple(item["exceptions"]),
            temporal=item["temporal"], coordination=item["coordination"], choice=item["choice"],
            support=tuple(ExtractiveRef("user_request", 0, len(quote), quote) for quote in support),
            unresolved_fields=tuple(item["unresolved"]),
            alternatives=tuple(item.get("alternatives") or ()))
        canonical_frames.append(frame)
    return GoalContract("goal:conservative:r0", "conservative", tuple(canonical_frames),
                        tuple(dict.fromkeys(unresolved_terms)))


def compiled_goal_closure_key(rules, unresolved=()) -> str:
    """Canonical closure key over COMPILED goal rules: the action_key is
    normalized to the deterministic key derived from the rule's primary
    source quote, so free-form content_key variance between frontends cannot
    break closure matching. Scope/conditions/temporal/alternatives remain."""
    from ..integrity import digest
    rows = []
    for rule in rules:
        quote = rule.source_quotes[0] if rule.source_quotes else ""
        rows.append({"kind": rule.kind, "modality": rule.modality,
                     "action_key": _key_from(quote, None) if quote else rule.action_key,
                     "scope": sorted([[field, sorted(values)] for field, values in rule.scope]),
                     "conditions": sorted([[c.key, c.negated] for c in rule.conditions]),
                     "exceptions": sorted([[c.key, c.negated] for c in rule.exceptions]),
                     "alternatives": sorted(rule.alternatives),
                     "unresolved": sorted(rule.unresolved_terms)})
    return digest({"rules": sorted(rows, key=canonical), "unresolved": sorted(unresolved or ())})

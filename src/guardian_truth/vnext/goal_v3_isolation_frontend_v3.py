"""Format-only intervention: full schema, unchanged v2 candidate semantics."""

from dataclasses import asdict

from .goal_v3_isolation_frontend_v2 import (
    SCHEMA, SYSTEM_PROMPT as V2_SYSTEM_PROMPT, grounding_payload_v2,
    prompt_messages_v2, proposal_issues_v2,
)
from .integrity import canonical, digest
from .schema_diagnostics import schema_issues, json_type

VERSION = "guardian-goal-v3-isolation-frontend-v3-full-schema"
SYSTEM_PROMPT = V2_SYSTEM_PROMPT + """
The following JSON Schema is the exact output contract. All required keys must
be present. Truth atoms are uppercase STRINGS, e.g. "TRUE", not JSON booleans.
authorization_closed, history_complete, complete_world_inventory and
decisive_for_no_error are JSON BOOLEANS true/false, never strings.
rule_outcomes, temporal_status and effects are OBJECT maps (empty {}).
obligations, unknowns, violations, evidence_ids, source_refs and worlds are
ARRAYS (empty [] only when the schema allows it). World unknowns are objects;
top-level unknowns are strings. Do not serialize JSON inside a string.
Return only one JSON object matching this schema, with no reasoning text.
JSON_SCHEMA:
""" + canonical(SCHEMA).decode("utf-8")
PROMPT_SHA256 = digest({"version": VERSION, "system": SYSTEM_PROMPT})
SCHEMA_SHA256 = digest(SCHEMA)


def prompt_messages_v3(source):
    messages = prompt_messages_v2(source)  # same Goal-only/data boundary
    messages[0] = {"role": "system", "content": SYSTEM_PROMPT}
    return messages


def proposal_issues_v3(value):
    """Value-free schema-owned paths; dynamic keys are never logged."""
    issues = [asdict(issue) for issue in schema_issues(value, SCHEMA)]
    if isinstance(value, dict):
        for field in ("rule_outcomes", "temporal_status", "effects"):
            mapping = value.get(field)
            if isinstance(mapping, dict):
                allowed = SCHEMA["properties"][field]["additionalProperties"]["enum"]
                for key, item in mapping.items():
                    if not isinstance(key, str) or not key or not isinstance(item, str) or item not in allowed:
                        issues.append({"code": "DYNAMIC_MAP_VALUE", "path": "/" + field + "/*",
                            "expected_type": "string", "actual_type": json_type(item)})
    if not issues:
        # Validity must remain identical to frozen v2, not a permissive repair.
        issues = [{"code": code, "path": "", "expected_type": None, "actual_type": None}
                  for code in proposal_issues_v2(value)]
    return tuple(issues)

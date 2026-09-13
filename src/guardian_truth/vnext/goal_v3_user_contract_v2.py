"""Replayable USER contract fragment, not open-vocabulary NL entailment.

The whole single USER message must parse. Assistant plans and tool output
text never supply governing clauses. Unsupported text causes abstention;
recognized spans are not silently extracted from a larger unknown message.
Catalog entries bind interface identity only, not goal/effect authority.
"""

from dataclasses import dataclass
import re

from .integrity import digest


ENTITY = r"[A-Za-z][A-Za-z0-9_-]{0,63}"
TOOL = r"[a-z][a-z0-9_]{0,63}"
GOAL = re.compile(rf"(?P<verb>Read|Check|Show|Get) (?:the )?(?P<field>status|details|content) of (?P<entity>{ENTITY})\.")
TOOLS = rf"{TOOL}(?: or {TOOL})*"
CLAUSES = (
    ("DIRECT_TOOLS", re.compile(rf"Use (?P<tools>{TOOLS}) for (?P<entity>{ENTITY})\.")),
    ("AUXILIARY_TOOLS", re.compile(rf"You may call (?P<tools>{TOOLS}) for (?P<entity>{ENTITY})\.")),
    ("FORBID_ATTEMPT", re.compile(rf"Never call (?P<required>{TOOL}) for (?P<entity>{ENTITY})\.")),
    ("REQUIRE_ATTEMPT_BEFORE", re.compile(rf"Before calling (?P<trigger>{TOOL}) for (?P<entity>{ENTITY}), call (?P<required>{TOOL}) for (?P=entity)\.")),
    ("REQUIRE_RESULT_TRUE", re.compile(rf"Before calling (?P<trigger>{TOOL}) for (?P<entity>{ENTITY}), (?P<required>{TOOL}) must return (?P<field>{TOOL})=true for (?P=entity)\.")),
    ("WHEN_RESULT_TRUE_REQUIRE_ATTEMPT", re.compile(rf"If the fresh result of (?P<guard>{TOOL}) for (?P<entity>{ENTITY}) has (?P<field>{TOOL})=true, call (?P<required>{TOOL}) for (?P=entity) before calling (?P<trigger>{TOOL}) for (?P=entity)\.")),
    ("REQUIRE_EFFECT_BY_SESSION", re.compile(rf"Before the session ends, complete (?P<required>{TOOL}) for (?P<entity>{ENTITY})\.")),
    ("CLOSE_AUTHORIZATION", re.compile(rf"Only the explicitly allowed calls for (?P<entity>{ENTITY}) are permitted\.")),
)


@dataclass(frozen=True)
class UserClauseV2:
    rule_id: str
    kind: str
    message_id: str
    span_start: int
    span_end: int
    span_text: str
    entity: str
    tools: tuple[str, ...] = ()
    trigger_tool: str | None = None
    required_tool: str | None = None
    guard_tool: str | None = None
    result_field: str | None = None


@dataclass(frozen=True)
class UserContractV2:
    schema_version: str
    source_sha256: str
    message_id: str
    desired_field: str
    entity: str
    goal_span_start: int
    goal_span_end: int
    goal_span_text: str
    clauses: tuple[UserClauseV2, ...]
    interface_bindings: tuple[tuple[str, str, str], ...]
    language_scope: str = "EXACT_SINGLE_USER_CONTRACT_FRAGMENT_V2"


def parse_user_contract_v2(source) -> UserContractV2 | None:
    """Return typed source authority only on complete fragment recognition."""
    if not isinstance(source, dict) or any(key in source for key in ("policy", "gold", "reference")):
        return None
    messages, catalog = source.get("user_messages"), source.get("tool_catalog")
    if (not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], dict)
            or not isinstance(catalog, dict)):
        return None
    message = messages[0]
    text, mid = message.get("text"), message.get("message_id")
    if (message.get("role") != "user" or not isinstance(text, str)
            or not isinstance(mid, str) or not mid):
        return None
    goal = GOAL.match(text)
    if goal is None:
        return None
    entity, cursor, clauses = goal.group("entity"), goal.end(), []
    named_tools = set()
    while cursor < len(text):
        if text[cursor] != " ":
            return None
        cursor += 1
        recognized = None
        for kind, pattern in CLAUSES:
            match = pattern.match(text, cursor)
            if match:
                recognized = kind, match
                break
        if recognized is None:
            return None
        kind, match = recognized
        fields = match.groupdict()
        if fields["entity"] != entity:
            return None
        tools = tuple(fields.get("tools", "").split(" or ")) if "tools" in fields else ()
        if len(set(tools)) != len(tools):
            return None
        for tool in (*tools, fields.get("trigger"), fields.get("required"), fields.get("guard")):
            if tool:
                named_tools.add(tool)
        clauses.append(UserClauseV2(f"{mid}:clause:{len(clauses)}", kind, mid,
            match.start(), match.end(), match.group(), entity, tools,
            fields.get("trigger"), fields.get("required"), fields.get("guard"), fields.get("field")))
        cursor = match.end()
    bindings = []
    for name in sorted(named_tools):
        cap = catalog.get(name)
        if (not isinstance(cap, dict) or not isinstance(cap.get("provider"), str)
                or not cap["provider"] or not isinstance(cap.get("version"), str) or not cap["version"]):
            return None
        bindings.append((name, cap["provider"], cap["version"]))
    return UserContractV2("guardian-goal-v3-user-contract-v2", digest(source), mid,
        goal.group("field"), entity, goal.start(), goal.end(), goal.group(),
        tuple(clauses), tuple(bindings))


def check_user_contract_v2(contract, source) -> tuple[bool, tuple[str, ...]]:
    """Replay whole message and interface identities, not model judgement."""
    if not isinstance(contract, UserContractV2):
        return False, ("CONTRACT_TYPE",)
    replay = parse_user_contract_v2(source)
    if replay is None:
        return False, ("USER_LANGUAGE_OR_INTERFACE_UNSUPPORTED",)
    if contract != replay:
        return False, ("USER_CONTRACT_REPLAY_MISMATCH",)
    return True, ()

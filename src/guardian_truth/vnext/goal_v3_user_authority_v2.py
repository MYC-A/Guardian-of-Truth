"""A deliberately small, replayable USER-language authority fragment.

Only an exact single-message prohibition of a named tool call is recognized.
Everything else abstains; span membership alone never proves NL entailment.
This is a v2 building block, not a general USER-goal parser or Core adapter.
"""

from dataclasses import dataclass
import hashlib
import re

from .integrity import digest


_ENTITY = r"[A-Za-z][A-Za-z0-9_-]{0,63}"
_TOOL = r"[a-z][a-z0-9_]{0,63}"
_SINGLE = re.compile(
    rf"(?P<span>Never call (?P<tool>{_TOOL}) for (?P<entity>{_ENTITY})\.)")
_WITH_GOAL = re.compile(
    rf"(?:Read|Check|Show|Get) (?:the )?(?:status|details|content) of "
    rf"(?P<entity>{_ENTITY})\. "
    rf"(?P<span>Never call (?P<tool>{_TOOL}) for (?P=entity)\.)")


@dataclass(frozen=True)
class ForbiddenCallCertificateV2:
    schema_version: str
    source_sha256: str
    message_id: str
    user_text_sha256: str
    span_start: int
    span_end: int
    span_text: str
    tool: str
    entity: str
    provider: str
    version: str
    target_sha256: str
    witnessed_action: str = "ASSISTANT_TOOL_CALL_ATTEMPT"
    violation: str = "EXPLICIT_USER_FORBIDDEN_CALL"


def _recognized_source(source):
    if not isinstance(source, dict) or any(key in source for key in ("policy", "gold", "reference")):
        return None
    messages, target, catalog = (source.get("user_messages"), source.get("target_action"),
        source.get("tool_catalog"))
    if (not isinstance(messages, list) or len(messages) != 1
            or not isinstance(messages[0], dict) or not isinstance(target, dict)
            or not isinstance(catalog, dict)):
        return None
    message = messages[0]
    if (message.get("role") != "user" or not isinstance(message.get("message_id"), str)
            or not message["message_id"] or not isinstance(message.get("text"), str)):
        return None
    text = message["text"]
    match = _SINGLE.fullmatch(text) or _WITH_GOAL.fullmatch(text)
    if match is None:
        return None
    tool, entity = match.group("tool"), match.group("entity")
    capability = catalog.get(tool)
    if (not isinstance(capability, dict) or not isinstance(capability.get("provider"), str)
            or not capability["provider"] or not isinstance(capability.get("version"), str)
            or not capability["version"] or target.get("kind") != "tool_call"
            or target.get("actor") != "assistant" or target.get("tool") != tool
            or target.get("entity") != entity or target.get("provider") != capability["provider"]
            or target.get("version") != capability["version"]):
        return None
    return message, target, capability, match


def certify_forbidden_call_v2(source) -> ForbiddenCallCertificateV2 | None:
    """Certify only literal named-tool prohibition and matching current call."""
    recognized = _recognized_source(source)
    if recognized is None:
        return None
    message, target, capability, match = recognized
    text = message["text"]
    return ForbiddenCallCertificateV2(
        "guardian-goal-v3-user-forbidden-call-certificate-v2",
        digest(source), message["message_id"], hashlib.sha256(text.encode("utf-8")).hexdigest(),
        match.start("span"), match.end("span"), match.group("span"),
        match.group("tool"), match.group("entity"),
        capability["provider"], capability["version"], digest(target))


def check_forbidden_call_certificate_v2(certificate, source) -> tuple[bool, tuple[str, ...]]:
    """Replay the exact USER string, catalog binding and current action."""
    if not isinstance(certificate, ForbiddenCallCertificateV2):
        return False, ("CERTIFICATE_TYPE",)
    replay = certify_forbidden_call_v2(source)
    if replay is None:
        return False, ("NO_RECOGNIZED_USER_AUTHORITY_OR_MATCHING_ACTION",)
    if certificate != replay:
        return False, ("SOURCE_OR_ACTION_REPLAY_MISMATCH",)
    return True, ()

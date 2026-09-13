"""Source-owned external step views, not Goal semantics or a verdict frontend.

Call arguments are structural action data, not factual response assertions.
The source format supplies step roles/pairing; embedded text never does.
"""

from dataclasses import dataclass

from .integrity import canonical, digest
from .source_envelope_v4 import SourceEnvelope, SourceFrame
from .types import Span, ToolIdentity

FIELDS = {"case_id", "policy_or_normative_context", "history_prefix", "tool_schemas", "target_assistant_turn"}
LIMITATIONS = (
    "application owns the supplied source-format mapping; hashes do not establish authorship",
    "declared goal authority is an explicit caller premise, not inferred from document wording",
    "a declared plan is source text, not proof of mandatory ordering",
    "source-derived signatures are not business contracts or actual provider schema hashes",
    "observed tool fields are not automatically confirmed business effects",
    "non-call action payloads are structural data, not silently treated as factual text",
    "prefix length alone does not prove relevant history completeness",
)


@dataclass(frozen=True)
class ExternalSourceViewsV6:
    source_sha256: str
    text_envelope: SourceEnvelope
    action_envelope: SourceEnvelope
    target_action_json: str
    target_action_span: Span
    target_call_identity: ToolIdentity | None
    signature_catalog_json: str
    declared_goal_actor: str
    declared_plan_actor: str
    limitations: tuple[str, ...] = LIMITATIONS
    scope: str = "EXPLICIT_SOURCE_FORMAT_PROJECTION_NOT_SEMANTIC_AUTHORITY_OR_CORE_VERDICT"


def _tool(action):
    name = action.get("name")
    if not isinstance(name, str) or not name or not isinstance(action.get("args"), dict):
        raise ValueError("source tool call requires explicit name and argument object")
    # The frozen signature catalogue describes observed arguments, not the real
    # provider schema. Do not use its hash as a ToolIdentity schema hash.
    # Extra provider/version/hash fields authored in an agent action are not
    # authenticated provider metadata in this source format. Preserve them in
    # structural source data, but do not turn them into trusted tool identity.
    return ToolIdentity(name)


def make_external_source_views_v6(case, *, declared_goal_actor, declared_plan_actor="unknown",
        history_complete=False, completeness_basis=None):
    """Adapt a label-free external format, requiring explicit authority premises.

    This does not read a dataset, choose cases, localize a drift step or access
    labels. It accepts both the Cycle2 safe projection and the vNext safe shape.
    Both views retain original source bodies; their deterministic projection hash
    includes the full input plus caller authority/completeness assumptions.
    """
    if not isinstance(case, dict) or set(case) != FIELDS:
        raise ValueError("exact label-free external source fields required")
    if declared_goal_actor not in {"user", "system", "unknown"}:
        raise ValueError("explicit source declaration authority required")
    if declared_plan_actor not in {"user", "system", "assistant", "unknown"}:
        raise ValueError("explicit plan-source authority or conservative unknown required")
    if (type(history_complete) is not bool
            or history_complete and (not isinstance(completeness_basis, str) or not completeness_basis)):
        raise ValueError("complete relevant history requires an explicit source premise")
    normative = case["policy_or_normative_context"]
    if not isinstance(normative, dict) or set(normative) != {"declared_goal", "declared_plan"}:
        raise ValueError("explicit declared goal/plan source shape required")
    if not isinstance(normative["declared_goal"], str) or not isinstance(normative["declared_plan"], list):
        raise ValueError("source goal text and plan list required")
    if any(not isinstance(item, str) for item in normative["declared_plan"]):
        raise ValueError("plan entries must be source text")
    history, signatures, target = case["history_prefix"], case["tool_schemas"], case["target_assistant_turn"]
    if not isinstance(history, list) or not isinstance(signatures, list) or not isinstance(target, dict):
        raise ValueError("explicit source prefix, signatures and target required")
    if set(target) != {"thought", "action"}:
        raise ValueError("target may not contain observations, labels or localization metadata")
    prompt, frames = "", []

    def append(body, actor, kind="text", tool=None, transport=None, requestor=None):
        nonlocal prompt
        span = Span("prompt", len(prompt), len(prompt) + len(body))
        if not body:
            return
        frames.append(SourceFrame(span, span, actor, kind, tool, transport, requestor))
        prompt += body + "\n"

    append(canonical({"declared_goal": normative["declared_goal"]}).decode(), declared_goal_actor)
    append(canonical({"declared_plan": normative["declared_plan"]}).decode(), declared_plan_actor)
    for index, step in enumerate(history):
        if (not isinstance(step, dict) or set(step) - {"index", "thought", "action", "observation"}
                or step.get("index") != index or type(step.get("index")) is not int):
            raise ValueError("source history requires contiguous explicit step indices")
        if not isinstance(step.get("thought"), str) or not isinstance(step.get("action"), dict):
            raise ValueError("source step thought/action shape required")
        append(step["thought"], "assistant")
        action = step["action"]
        if action.get("type") == "tool_call":
            identity, transport = _tool(action), "source-step:" + str(index)
            append(canonical(action["args"]).decode(), "assistant", "call", identity, transport, "assistant")
            if "observation" in step:
                observation = step["observation"]
                # A JSON-looking string remains a string; no nested parsing or
                # extraction of apparent SYSTEM instructions is authorized.
                payload = observation if isinstance(observation, dict) else {"observation": observation}
                append(canonical(payload).decode(), "tool", "result", identity, transport, "assistant")
        else:
            if not isinstance(action.get("type"), str) or not action["type"]:
                raise ValueError("explicit source action type required")
            append(canonical(action).decode(), "assistant")
            if "observation" in step:
                append(canonical({"environment_observation": step["observation"]}).decode(), "unknown")
    thought, action = target["thought"], target["action"]
    if not isinstance(thought, str) or not isinstance(action, dict) or not isinstance(action.get("type"), str) or not action["type"]:
        raise ValueError("explicit target thought and action type required")
    identity = _tool(action) if action["type"] == "tool_call" else None
    # Text view has no target call/result: completion assertions are checked
    # against the prefix, not against an invented current-action outcome.
    text_frames = tuple(frames)
    if thought:
        span = Span("response", 0, len(thought))
        text_frames += (SourceFrame(span, span, "assistant", "text"),)
    source_hash = digest({"case": case, "declared_goal_actor": declared_goal_actor,
        "declared_plan_actor": declared_plan_actor,
        "history_complete": history_complete, "completeness_basis": completeness_basis})
    provenance = "application external source-format projection sha256=" + source_hash + "; original step association supplies pairing"
    text_envelope = SourceEnvelope(prompt, thought, text_frames, "external-source-views", "v6-text", provenance,
        history_complete, completeness_basis)
    target_body = canonical(action["args"] if identity else action).decode()
    action_response = thought + ("\n" if thought else "") + target_body
    action_span = Span("response", len(action_response) - len(target_body), len(action_response))
    action_frames = text_frames + (SourceFrame(action_span, action_span, "assistant", "call" if identity else "text",
        identity, "source-target" if identity else None, "assistant" if identity else None),)
    action_envelope = SourceEnvelope(prompt, action_response, action_frames, "external-source-views", "v6-action", provenance,
        history_complete, completeness_basis)
    return ExternalSourceViewsV6(source_hash, text_envelope, action_envelope, canonical(action).decode(), action_span,
        identity, canonical(signatures).decode(), declared_goal_actor, declared_plan_actor)


def validate_external_source_views_v6(views, case, *, declared_goal_actor, declared_plan_actor="unknown",
        history_complete=False, completeness_basis=None):
    """Replay source projection only; never validate NL meaning or a verdict."""
    if not isinstance(views, ExternalSourceViewsV6):
        return False
    try:
        return views == make_external_source_views_v6(case, declared_goal_actor=declared_goal_actor,
            declared_plan_actor=declared_plan_actor,
            history_complete=history_complete, completeness_basis=completeness_basis)
    except (ValueError, TypeError):
        return False

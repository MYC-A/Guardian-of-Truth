"""Deterministic ToolResult classification from payload shape only.

The classifier never sees the tool name, the tool description, or any
natural-language narrative. It answers one question: what KIND of result is
this? Business meaning is assigned later by contracts or witnessed proposals.

Rules are ordered and total: every decodable payload receives exactly one
ResultType.
"""

from __future__ import annotations

import json
import math
from typing import Any

from .types import ResultType

ASYNC_VALUES = {
    "queued", "queue", "processing", "processed_async", "pending",
    "scheduled", "accepted", "submitted", "in_progress", "started",
    "initiated", "request_created", "created", "requested", "received",
}

FAILURE_KEYS = {"error", "error_message", "error_code", "exception", "reason"}
ACK_KEYS = {"success", "status_code", "code", "ok", "acknowledged", "ack", "message"}

# Fields that typically carry a business post-state (checked case-insensitively
# for the *presence* of state, never for the business meaning of values).
STATE_KEYS = {"status", "new_status", "current_status", "state", "new_state",
              "order_status", "reservation_status", "line_status", "ticket_status"}

# Success-ish boolean payloads.
_SUCCESS_TRUE = {"true", "1", "yes", "ok"}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=False)


def _has_failure_marker(payload: dict) -> bool:
    if any(key in payload for key in FAILURE_KEYS):
        return True
    for key in ("success", "ok", "completed", "done"):
        if key in payload and _canonical(payload[key]).lower() in ('false', '"false"', '0', '"no"', '"failed"', 'null'):
            return True
        if key in payload and payload[key] is False:
            return True
    return False


def _has_async_marker(payload: dict) -> bool:
    for key in STATE_KEYS:
        if key in payload:
            value = payload[key]
            if isinstance(value, str) and value.strip().lower().replace("-", "_").replace(" ", "_") in ASYNC_VALUES:
                return True
            # {"status": {"state": "queued"}} nested shapes
            if isinstance(value, dict):
                for sub in value.values():
                    if isinstance(sub, str) and sub.strip().lower() in ASYNC_VALUES:
                        return True
    for key in ("request_id", "request_status", "job_id", "task_id", "ticket_id"):
        if key in payload and isinstance(payload[key], str) and payload[key]:
            return True
    return False


def _has_business_state(payload: dict) -> bool:
    for key in STATE_KEYS:
        if key in payload and payload[key] is not None:
            return True
    return False


def _is_read_shaped(payload: dict) -> bool:
    """Entity-data shaped: has nested objects/arrays or ID-ish keys, no ack keys."""
    has_ack = any(key in payload for key in ACK_KEYS)
    has_entity = any(
        isinstance(value, (dict, list)) for value in payload.values()
    ) or any(key.endswith("_id") or key.endswith("_ids") for key in payload)
    return has_entity and not has_ack


def classify_payload(payload: Any) -> ResultType:
    """Classify an already-decoded payload."""
    if payload is None:
        return ResultType.EMPTY
    if not isinstance(payload, dict):
        return ResultType.MALFORMED if payload else ResultType.EMPTY
    if not payload:
        return ResultType.EMPTY
    if _has_failure_marker(payload):
        # {"success": true, "error": null} is still a failure-shaped payload
        # only when the failure marker is present AND non-null.
        if all(payload.get(key) is None for key in payload if key in FAILURE_KEYS) and \
           not any(payload.get(k) is False for k in ("success", "ok", "completed", "done")):
            pass  # neutralised failure markers fall through
        else:
            return ResultType.FAILURE
    async_ = _has_async_marker(payload)
    state = _has_business_state(payload)
    read_shaped = _is_read_shaped(payload)
    ack_only = set(payload).issubset(ACK_KEYS | {"data"})
    if async_:
        return ResultType.ASYNC_ACCEPTED
    if state:
        return ResultType.BUSINESS_STATE
    if read_shaped:
        return ResultType.OBSERVATION
    if ack_only:
        success_values = [payload.get(k) for k in ("success", "ok") if k in payload]
        if any(v is True or _canonical(v).lower() in _SUCCESS_TRUE for v in success_values):
            return ResultType.SUCCESS_ACK
        return ResultType.EMPTY if all(v is None for v in payload.values()) else ResultType.UNKNOWN
    return ResultType.UNKNOWN


def classify_result_text(text: str | None) -> tuple[ResultType, Any]:
    """Decode raw result text then classify. Returns (type, decoded payload)."""
    if text is None:
        return ResultType.MALFORMED, None
    stripped = (text or "").strip()
    if not stripped:
        return ResultType.EMPTY, None
    try:
        payload = json.loads(stripped)
    except (ValueError, TypeError, RecursionError):
        return ResultType.MALFORMED, None
    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        return ResultType.MALFORMED, None
    if isinstance(payload, list):
        return ResultType.MALFORMED, None
    return classify_payload(payload), payload


def json_path_get(payload: Any, path: str) -> tuple[Any, bool]:
    """Resolve a '$.a.b[0].c' style path; returns (value, present)."""
    if not path.startswith("$"):
        return None, False
    rest = path[1:]
    tokens: list[tuple[str, int | None]] = []
    for raw in [seg for seg in rest.split(".") if seg]:
        name = raw
        index = None
        if "[" in raw and raw.endswith("]"):
            name, idx = raw[:-1].split("[", 1)
            try:
                index = int(idx)
            except ValueError:
                return None, False
        tokens.append((name, index))
    current = payload
    for name, index in tokens:
        if name:
            if not isinstance(current, dict) or name not in current:
                return None, False
            current = current[name]
        if index is not None:
            if not isinstance(current, list) or index >= len(current) or index < 0:
                return None, False
            current = current[index]
    return current, True


def scalar_to_json(value: Any) -> str | None:
    """Canonical scalar rendering; refuses non-scalars (facts cite exact fields)."""
    if value is None or isinstance(value, bool) or isinstance(value, str):
        return _canonical(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return repr(value)
    return None

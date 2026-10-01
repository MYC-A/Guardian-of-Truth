#!/usr/bin/env python3
"""Guardian service audit: trace ids + append-only JSONL."""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

_LOCK = threading.Lock()


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def append_jsonl(path: Path, record: dict) -> bool:
    """Append-only JSONL write, thread-safe, best-effort (audit failure
    must not lose the decision itself; it is surfaced by the caller)."""
    try:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return True
    except OSError:
        return False


def audit_record(trace_id: str, config_id: str, case_id: str,
                 decision: str, decision_basis: str, findings_n: int,
                 usage: dict, degraded: bool, reasons: list,
                 wall_s: float) -> dict:
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "trace_id": trace_id,
        "config_id": config_id,
        "case_id": case_id,
        "decision": decision,
        "decision_basis": decision_basis,
        "findings": findings_n,
        "usage": usage,
        "degraded": degraded,
        "reasons": reasons,
        "wall_s": round(wall_s, 3),
    }

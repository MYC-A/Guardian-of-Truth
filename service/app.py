#!/usr/bin/env python3
"""Guardian check service — minimal FastAPI app (directive §13, Stage A).

Endpoints:
  GET  /health            — liveness of the process (no model probing);
  GET  /ready             — per-channel readiness (structural always;
                            judge channels as configured);
  GET  /v1/configs        — available frozen experiment configs;
  POST /v1/check          — one {case_id, prompt, response} check;
  POST /v1/check/batch    — many cases in one call (bounded by queue).

Run (local, structural-only — works with no API keys):
    uvicorn service.app:app --host 0.0.0.0 --port 8090
Run (v6-judges — needs the three_architectures API env):
    GUARDIAN_CONFIG=v6-judges uvicorn service.app:app --port 8090
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

SERVICE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVICE_DIR))

from runtime import (GuardianServiceRuntime,  # noqa: E402
                     list_configs)
from dispatch import BoundedDispatcher, RequestTimedOut

DEFAULT_CONFIG = os.environ.get("GUARDIAN_CONFIG", "structural-v02")
AUDIT_PATH = Path(os.environ.get(
    "GUARDIAN_AUDIT_PATH", str(SERVICE_DIR / "audit.jsonl")))
MAX_QUEUE = int(os.environ.get("GUARDIAN_MAX_QUEUE", "8"))
QUEUE_TIMEOUT_S = float(os.environ.get("GUARDIAN_QUEUE_TIMEOUT_S", "60"))

app = FastAPI(title="Guardian check service", version="0.1.0-stageA")

_runtime = GuardianServiceRuntime(DEFAULT_CONFIG, audit_path=AUDIT_PATH)
_started = time.time()
_queue_full_events = 0
_dispatcher = BoundedDispatcher(
    workers=int(os.environ.get("GUARDIAN_WORKERS", "1")),
    max_waiting=MAX_QUEUE, queue_timeout_s=QUEUE_TIMEOUT_S)


class CheckRequest(BaseModel):
    case_id: str = "unnamed"
    prompt: str
    response: str
    config_id: str | None = None


class BatchRequest(BaseModel):
    cases: list[CheckRequest] = Field(min_length=1, max_length=64)
    config_id: str | None = None


def _runtime_for(config_id: str | None) -> GuardianServiceRuntime:
    if config_id is None or config_id == _runtime.config_id:
        return _runtime
    try:
        return GuardianServiceRuntime(config_id, audit_path=AUDIT_PATH)
    except KeyError:
        raise HTTPException(404, f"unknown config: {config_id}") from None


@app.get("/health")
def health() -> dict:
    return {"status": "alive", "pid": os.getpid(),
            "uptime_s": round(time.time() - _started, 1),
            "config_id": _runtime.config_id}


@app.get("/ready")
def ready() -> dict:
    status = _runtime.channel_status()
    ready = all(bool(v) for v in status.values())
    return {"ready": ready, "channels": status,
            "channel_details": _runtime.channel_details,
            "config_id": _runtime.config_id}


@app.get("/v1/configs")
def configs() -> dict:
    return {"configs": list_configs(), "default": _runtime.config_id}


async def _execute(rt, payload):
    from audit import new_trace_id
    trace_id = new_trace_id()
    payload = dict(payload, _trace_id=trace_id)
    started = time.time()
    try:
        return await _dispatcher.run(rt.check, payload,
            timeout_s=float(rt.limits.get("request_timeout_s", 240)))
    except RequestTimedOut:
        return rt._finish(payload["case_id"], "UNKNOWN", "schema", [], [],
            {"request": "deadline_exceeded", "worker": "still_running_slot_retained"},
            True, trace_id, {"calls": 0, "tokens": 0,
                             "usage_status": "pending_worker_completion"}, started)


@app.post("/v1/check")
async def check(req: CheckRequest) -> dict:
    rt = _runtime_for(req.config_id)
    return await _execute(rt, {
        "case_id": req.case_id, "prompt": req.prompt,
        "response": req.response})


@app.post("/v1/check/batch")
async def check_batch(req: BatchRequest) -> dict:
    rt = _runtime_for(req.config_id)
    global _queue_full_events
    if len(req.cases) > MAX_QUEUE:
        _queue_full_events += 1
        raise HTTPException(
            429, f"batch too large: {len(req.cases)} > {MAX_QUEUE}")
    results = []
    for case in req.cases:
        res = await _execute(rt, {
            "case_id": case.case_id, "prompt": case.prompt,
            "response": case.response})
        results.append(res)
    decisions = [r["decision"] for r in results]
    return {"n": len(results),
            "error": decisions.count("ERROR"),
            "no_error": decisions.count("NO_ERROR"),
            "unknown": decisions.count("UNKNOWN"),
            "degraded": sum(1 for r in results if r.get("degraded")),
            "results": results}

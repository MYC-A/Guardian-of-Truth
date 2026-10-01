"""One native specialist as an advisory to independent B, after direct J.

Exact frozen dev scores are reusable only for identical source/claim. New
cases score on GPU, one locked resident checkpoint per process. Mixed targets
and long sources are explicitly unsupported; no support score decides ERROR.
"""
from __future__ import annotations
import hashlib
import json
import threading
import time
from pathlib import Path

from candidate_bank import candidate_for

ROOT = Path(__file__).resolve().parents[3]
_LOCK = threading.Lock()
_ACTIVE = {}
_REPLAYS = {}


def _records(cfg):
    replay = cfg.get("replay")
    if not replay:
        return {}
    digest = replay["sha256"]
    if digest not in _REPLAYS:
        path = ROOT / replay["results_file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("native replay hash mismatch")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        if len(rows) != len({r["id"] for r in rows}):
            raise ValueError("duplicate native replay ID")
        _REPLAYS[digest] = {r["id"]: r for r in rows}
    return _REPLAYS[digest]


def native_advisory(cfg, ctx):
    began = time.monotonic()
    row = candidate_for({"id": ctx.case_id, "prompt": ctx.prompt_raw,
                         "response": ctx.response_raw})
    identity = {"module": "native-advisory/1", "model": cfg["model"],
                "claim": row["claim"], "claim_kind": row["claim_kind"],
                "target_quote": row["target_quote"],
                "source_sha256": row["source_sha256"],
                "scope": "support/risk for this candidate; not a Guardian verdict"}
    if (row["claim_kind"] == "mixed_or_unparsed_target" or
            len(row["document"].split()) > cfg.get("max_source_words", 500)):
        return "", {**identity, "status": "UNSUPPORTED", "reason": "mixed_or_long_source"}
    with _LOCK:
        prior = _records(cfg).get(ctx.case_id)
        if (prior is not None and prior["source_sha256"] == row["source_sha256"] and
                prior["claim"] == row["claim"] and prior["model"] == cfg["model"]):
            result = {"support_score": prior["support_score"],
                      "native_output": prior.get("native_output")}
            origin = "FROZEN_EXACT_SOURCE_REPLAY"
        else:
            if _ACTIVE and _ACTIVE["model"] != cfg["model"]:
                return "", {**identity, "status": "UNAVAILABLE",
                    "reason": "different_checkpoint_already_resident"}
            if not _ACTIVE:
                from specialist_run import load_checker
                score_fn, device = load_checker(cfg["model"])
                _ACTIVE.update({"model": cfg["model"], "score": score_fn,
                                "device": str(device)})
            result = _ACTIVE["score"](row["document"], row["claim"])
            origin = "LIVE_NATIVE_GPU"
    record = {**identity, **result, "origin": origin,
              "elapsed_s": round(time.monotonic() - began, 3),
              "status": "MODEL_SIGNAL" if result["support_score"] is not None else "INVALID",
              "warning": "This score is not calibrated truth. Source entailment does not certify full move correctness."}
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")), record

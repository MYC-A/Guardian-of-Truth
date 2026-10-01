#!/usr/bin/env python3
"""Guardian service runtime — the frozen-config check pipeline.

Stage A (directive §13, 2026-10-01): a minimal, working service on the
EXISTING baseline:
  * deterministic layer = the corrected structural channel v0.2
    (hybrid_service_v1.structural_v02) over the frozen lossless
    official-format parser (three_architectures.common);
  * model layer (optional, config `v6-judges`) = the PRE-REGISTERED V6
    two-judge rule: one vote per family (gemma, mistral), third checker
    (gpt-oss) ONLY on disagreement or an invalid vote; an unavailable
    channel degrades the case to UNKNOWN — never a silent drop or a
    silent 0 (PREREGISTERED_PROTOCOL.md, 2026-10-01).

Decision semantics (honest by construction):
  ERROR    — at least one confirmed finding (structural hit or a judged
             new error of the target move);
  NO_ERROR — only available in a configuration whose stages actually
             cover the semantics (judge consensus 0 with valid votes);
             a clean structural scan alone is UNKNOWN: mechanical absence
             is not a certificate of correctness;
  UNKNOWN  — coverage gap, invalid votes after the allowed re-ask,
             unavailable channel, or input beyond the context budget.

Findings carry: type, checked object (call/statement), verbatim quotes
with source refs, entity/time binding, status, and the module that
produced them. Nothing in this runtime reads gold or tunes thresholds.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent
REPO = SERVICE_DIR.parent
sys.path.insert(0, str(REPO / "experiments/searh_23/hybrid_service_v1"))
sys.path.insert(0, str(REPO / "experiments/searh_23/three_architectures"))

from structural_v02 import parse_case_v02  # noqa: E402


# ------------------------------------------------------------------ configs

def load_config(config_id: str) -> dict:
    path = SERVICE_DIR / "configs" / f"{config_id}.json"
    if not path.exists():
        raise KeyError(f"unknown frozen config: {config_id}")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if cfg.get("config_id") != config_id:
        raise ValueError(f"config id mismatch in {path}")
    return cfg


def list_configs() -> list:
    return sorted(p.stem for p in (SERVICE_DIR / "configs").glob("*.json"))


# ----------------------------------------------------------------- findings

def structural_findings(ctx) -> list:
    """Findings from confirmed structural hits — mechanical, reproducible,
    each with its verbatim basis and source refs."""
    out = []
    for h in ctx.structural_hits:
        out.append({
            "type": h.reason,
            "checked": {
                "object": "tool_call" if h.tool else "response",
                "tool": h.tool,
                "call_ids": h.call_id.split(",") if h.call_id else [],
            },
            "quotes": [{"source": "policy_or_catalog", "text": h.basis}],
            "binding": {"turn": "target", "call_ids": h.call_id},
            "arguments_for": [h.basis],
            "arguments_against": [],
            "status": "CONFIRMED",
            "module": "structural_v02",
        })
    return out


def suspicion_notes(ctx) -> list:
    return [{"kind": s.kind, "detail": s.detail,
             "evidence_refs": list(s.evidence_refs)}
            for s in ctx.suspicions]


# ------------------------------------------------------------- judge layer

def _judge_stage(cfg_judges: dict, ctx) -> tuple:
    """The pre-registered V6 rule. Returns (decision, findings, usage,
    degraded, reasons). Requires the three_architectures llm/judge stack;
    import errors or unavailable channels degrade to UNKNOWN."""
    reasons: list = []
    usage = {"calls": 0, "tokens": 0}
    try:
        import judge as judge_mod  # noqa: PLC0415  (lazy: needs API env)
        from llm import available, chat  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        return ("UNKNOWN", [], usage, True,
                [f"channel_error:stack_import:{type(e).__name__}: "
                 f"{getattr(e, 'name', '')}".rstrip(":")])
    votes = []
    for slot, model in ((1, cfg_judges["j1_model"]),
                        (2, cfg_judges["j2_model"])):
        try:
            rec = judge_mod.ask_vote(
                model, ctx, slot=slot, seed=None,
                temperature=cfg_judges.get("temperature", 0.0),
                max_tokens=cfg_judges.get("max_tokens", 1500),
                max_context_chars=cfg_judges.get("max_context_chars", 12000),
                caller="service/v6")
        except Exception as e:  # noqa: BLE001
            return ("UNKNOWN", [], usage, True,
                    [f"channel_error:{model}:{type(e).__name__}"])
        usage["calls"] += len(rec.get("attempts", []))
        u = rec.get("usage") or {}
        usage["tokens"] += int(u.get("total_tokens") or 0)
        usage.setdefault("prompt_tokens", 0)
        usage["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
        usage.setdefault("completion_tokens", 0)
        usage["completion_tokens"] += int(u.get("completion_tokens") or 0)
        votes.append(rec)

    v1, v2 = votes[0], votes[1]
    if v1["valid"] and v2["valid"] and v1["vote"]["label"] == v2["vote"]["label"]:
        label = v1["vote"]["label"]
        if label == 1:
            return ("ERROR", _judge_findings([v1, v2]), usage, False, [])
        return ("NO_ERROR", [], usage, False, [])

    # disagreement or an invalid vote -> third checker (family gpt-oss)
    model3 = cfg_judges["third_model"]
    try:
        rec3 = judge_mod.ask_vote(
            model3, ctx, slot=3, seed=None,
            temperature=cfg_judges.get("temperature", 0.0),
            max_tokens=cfg_judges.get("max_tokens", 1500),
            max_context_chars=cfg_judges.get("max_context_chars", 12000),
            caller="service/v6")
    except Exception as e:  # noqa: BLE001
        return ("UNKNOWN", [], usage, True,
                [f"channel_error:third:{type(e).__name__}"])
    usage["calls"] += len(rec3.get("attempts", []))
    u3 = rec3.get("usage") or {}
    usage["tokens"] += int(u3.get("total_tokens") or 0)
    usage["prompt_tokens"] += int(u3.get("prompt_tokens") or 0)
    usage["completion_tokens"] += int(u3.get("completion_tokens") or 0)
    if rec3["valid"]:
        label = rec3["vote"]["label"]
        if label == 1:
            return ("ERROR", _judge_findings([rec3]), usage, False,
                    ["third_checker_decided"])
        return ("NO_ERROR", [], usage, False, ["third_checker_decided"])
    return ("UNKNOWN", [], usage, True,
            ["third_checker_invalid_after_reask"])


def _judge_findings(vote_records: list) -> list:
    """Findings from the deciding vote: quoted evidence with source refs."""
    out = []
    for rec in vote_records:
        if not rec.get("valid"):
            continue
        vote = rec.get("vote") or {}
        if vote.get("label") != 1:
            continue
        # judge.validate_vote has already checked the target quote and, for
        # CONTRADICTION, a verbatim quote in the relevant source. The vote
        # schema is flat; it has no `evidence` or `error_type` field.
        quotes = [{"source": source, "text": vote[key]}
                  for key, source in (("response_quote", "response"),
                                      ("policy_quote", "policy"),
                                      ("history_quote", "history"),
                                      ("catalog_quote", "catalog"))
                  if isinstance(vote.get(key), str) and vote[key].strip()]
        out.append({
            "type": vote["type"].upper(),
            "checked": {"object": "target_move",
                        "statement": vote["response_quote"]},
            "quotes": quotes,
            "binding": {"turn": "target",
                        "source_refs": list(vote.get("source_refs") or [])},
            "arguments_for": [vote["explanation"]],
            "arguments_against": [],
            "status": "JUDGED",
            "module": f"judge/{rec.get('model')}",
        })
    return out


# ------------------------------------------------------------------ runtime

class GuardianServiceRuntime:
    def __init__(self, config_id: str = "structural-v02",
                 audit_path: Path | None = None):
        self.config = load_config(config_id)
        self.config_id = self.config["config_id"]
        self.audit_path = audit_path
        self.limits = self.config.get("limits", {})
        self._readiness_cache: dict[str, tuple[float, bool, str]] = {}
        self.channel_details: dict = {}

    # -------------------------------------------------------------- helpers

    def channel_status(self) -> dict:
        """Cached, non-inference backend probe for /ready.

        Credential presence is reported separately from reachability; GET
        /models never generates a model answer. Probes occur only when /ready
        is requested and are cached for 60 seconds.
        """
        status = {"structural": True, "parser": True}
        self.channel_details = {}
        judges = self.config.get("stages", {}).get("judges")
        if judges:
            try:
                from llm import (MODEL_REGISTRY, PROVIDERS,  # noqa: PLC0415
                                 GRANITE_LOCAL_PATH)
                models = {judges[k] for k in
                          ("j1_model", "j2_model", "third_model")}
                providers = {MODEL_REGISTRY.get(m, m.split("/", 1)[0])
                             for m in models}
                for provider in sorted(providers):
                    if provider == "granite-local":
                        ok = GRANITE_LOCAL_PATH.exists()
                        detail = {"configured": ok, "reachable": ok,
                                  "reason": "local_path_present" if ok else
                                            "local_path_absent"}
                    elif provider in PROVIDERS:
                        base, key = PROVIDERS[provider]
                        configured = bool(key)
                        if configured:
                            ok, reason = self._probe_backend(provider,
                                                             base, key)
                        else:
                            ok, reason = False, "credential_absent"
                        detail = {"configured": configured,
                                  "reachable": ok, "reason": reason}
                    else:
                        ok = False
                        detail = {"configured": False, "reachable": False,
                                  "reason": "unknown_provider"}
                    status[provider] = ok
                    self.channel_details[provider] = detail
            except Exception as exc:  # noqa: BLE001
                status["judge_stack"] = False
                self.channel_details["judge_stack"] = {
                    "configured": False, "reachable": False,
                    "reason": f"probe_setup:{type(exc).__name__}"}
        return status

    def _probe_backend(self, provider: str, base: str, key: str) -> tuple[bool, str]:
        now = time.monotonic()
        cached = self._readiness_cache.get(provider)
        if cached and now - cached[0] < 60:
            return cached[1], cached[2]
        request = urllib.request.Request(
            base.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {key}"}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                ok, reason = 200 <= response.status < 300, f"http_{response.status}"
        except urllib.error.HTTPError as exc:
            ok, reason = False, f"http_{exc.code}"
        except Exception as exc:  # noqa: BLE001
            ok, reason = False, f"transport:{type(exc).__name__}"
        self._readiness_cache[provider] = (now, ok, reason)
        return ok, reason

    # ----------------------------------------------------------- main entry

    def check(self, case: dict) -> dict:
        """case: {case_id, prompt, response}. Returns the §13 payload."""
        from audit import audit_record, new_trace_id

        t0 = time.time()
        trace_id = new_trace_id()
        case_id = str(case.get("case_id") or "unnamed")
        prompt = case.get("prompt") or ""
        response = case.get("response") or ""

        budget = int(self.limits.get("max_context_chars", 200000))
        if len(prompt) + len(response) > budget:
            payload = {
                "case_id": case_id,
                "decision": "UNKNOWN",
                "decision_basis": "schema",
                "config_id": self.config_id,
                "findings": [],
                "assumptions": [],
                "coverage": {"structural": "not_run",
                             "reason": "context_budget_exceeded",
                             "input_chars": len(prompt) + len(response),
                             "budget": budget},
                "degraded": True,
                "trace_id": trace_id,
                "usage": {"calls": 0, "tokens": 0},
            }
            if self.audit_path is not None:
                from audit import append_jsonl, audit_record
                append_jsonl(self.audit_path, audit_record(
                    trace_id, self.config_id, case_id, "UNKNOWN", "schema",
                    0, payload["usage"], True,
                    ["context_budget_exceeded"], time.time() - t0))
            return payload

        ctx = parse_case_v02(case_id, prompt, response)
        findings = structural_findings(ctx)
        usage = {"calls": 0, "tokens": 0}

        if findings:
            decision, basis = "ERROR", "schema"
            coverage = {"structural": "confirmed_hit"}
        else:
            judges = self.config.get("stages", {}).get("judges")
            if not judges:
                decision, basis = "UNKNOWN", "schema"
                coverage = {
                    "structural": "clean_scan",
                    "model": "not_configured",
                    "note": ("mechanical absence of structural hits is not "
                             "a certificate of correctness"),
                }
            else:
                decision, jf, usage, degraded, reasons = _judge_stage(
                    judges, ctx)
                findings.extend(jf)
                # structural was clean; the model layer decides
                basis = "model"
                if decision == "NO_ERROR":
                    coverage = {"structural": "clean_scan",
                                "model": "judge_consensus"}
                elif decision == "UNKNOWN":
                    coverage = {"structural": "clean_scan",
                                "model": "unavailable_or_invalid",
                                "reasons": reasons}
                else:  # ERROR
                    coverage = {"structural": "clean_scan",
                                "model": "judge_verdict"}
                return self._finish(case_id, decision, basis, findings,
                                    suspicion_notes(ctx), coverage,
                                    bool(degraded), trace_id, usage, t0)

        return self._finish(case_id, decision, basis, findings,
                            suspicion_notes(ctx), coverage, False,
                            trace_id, usage, t0)

    def _finish(self, case_id, decision, basis, findings, assumptions,
                coverage, degraded, trace_id, usage, t0) -> dict:
        from audit import append_jsonl, audit_record
        payload = {
            "case_id": case_id,
            "decision": decision,
            "decision_basis": basis,
            "config_id": self.config_id,
            "findings": findings,
            "assumptions": assumptions,
            "coverage": coverage,
            "degraded": degraded,
            "trace_id": trace_id,
            "usage": usage,
        }
        if self.audit_path is not None:
            append_jsonl(self.audit_path, audit_record(
                trace_id, self.config_id, case_id, decision, basis,
                len(findings), usage, degraded,
                [f.get("type", "") for f in findings],
                time.time() - t0))
        return payload

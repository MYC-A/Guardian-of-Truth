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
        vote = rec.get("vote") or {}
        if vote.get("label") != 1:
            continue
        for ev in (vote.get("evidence") or [])[:8]:
            out.append({
                "type": vote.get("error_type", "NEW_ERROR"),
                "checked": {"object": "target_move",
                            "statement": ev.get("statement", "")},
                "quotes": [
                    {"source": ev.get("source_ref", "response"),
                     "text": ev.get("response_quote", "")},
                    {"source": ev.get("contradicting_source_ref", ""),
                     "text": ev.get("contradicting_quote", "")},
                ],
                "binding": {"turn": "target"},
                "arguments_for": [ev.get("reason", "")],
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

    # -------------------------------------------------------------- helpers

    def channel_status(self) -> dict:
        """Booleans for /ready: which stages can run right now."""
        status = {"structural": True, "parser": True}
        judges = self.config.get("stages", {}).get("judges")
        if judges:
            try:
                from llm import available  # noqa: PLC0415
                av = available()
                status["mistral"] = bool(av.get("mistral"))
                status["ollama"] = bool(av.get("ollama"))
            except Exception:  # noqa: BLE001
                status["mistral"] = False
                status["ollama"] = False
        return status

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
            return {
                "case_id": case_id,
                "decision": "UNKNOWN",
                "decision_basis": "schema",
                "config_id": self.config_id,
                "findings": [],
                "assumptions": [],
                "coverage": {"structural": "not_run",
                             "reason": "context_budget_exceeded"},
                "degraded": True,
                "trace_id": trace_id,
                "usage": {"input_chars": len(prompt) + len(response)},
            }

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
                if decision == "ERROR":
                    basis = "model" if not findings else "hybrid"
                    # structural was clean; ERROR came from the model layer
                    basis = "model"
                elif decision == "NO_ERROR":
                    basis = "model"
                    coverage = {"structural": "clean_scan",
                                "model": "judge_consensus"}
                else:
                    basis = "model"
                    coverage = {"structural": "clean_scan",
                                "model": "unavailable_or_invalid",
                                "reasons": reasons}
                    return self._finish(case_id, decision, basis, findings,
                                        suspicion_notes(ctx), coverage, True,
                                        trace_id, usage, t0)
                return self._finish(case_id, decision, basis, findings,
                                    suspicion_notes(ctx), coverage, False,
                                    trace_id, usage, t0)

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

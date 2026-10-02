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
import hashlib
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent
REPO = SERVICE_DIR.parent
sys.path.insert(0, str(REPO / "src"))
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
    reviewer = cfg.get("stages", {}).get("counterevidence")
    if reviewer and reviewer.get("model") == "env_mistral":
        from llm import DEFAULT_MISTRAL_MODEL
        reviewer["resolved_model"] = DEFAULT_MISTRAL_MODEL
    return cfg


def list_configs() -> list:
    return sorted(p.stem for p in (SERVICE_DIR / "configs").glob("*.json"))


# ----------------------------------------------------------------- findings

def structural_findings(ctx) -> list:
    """Findings from confirmed structural hits — mechanical, reproducible,
    each with its verbatim basis and source refs."""
    out = []
    for h in ctx.structural_hits:
        target_lines = ctx.response_raw.splitlines()
        quotes = []
        call_ids = set(h.call_id.split(","))
        for call in ctx.target().tool_calls:
            if call.call_id not in call_ids or not 0 <= call.line_no < len(target_lines):
                continue
            target_line = target_lines[call.line_no].strip()
            if target_line:
                start = ctx.response_raw.find(target_line)
                quotes.append({"source": "response", "text": target_line,
                               "start": start, "end": start + len(target_line)})
        out.append({
            "type": h.reason,
            "checked": {
                "object": "tool_call" if h.tool else "response",
                "tool": h.tool,
                "call_ids": h.call_id.split(",") if h.call_id else [],
            },
            "quotes": quotes,
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
    ctx.judge_trace = []
    try:
        import judge as judge_mod  # noqa: PLC0415  (lazy: needs API env)
        from llm import available, chat  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        return ("UNKNOWN", [], usage, True,
                [f"channel_error:stack_import:{type(e).__name__}: "
                 f"{getattr(e, 'name', '')}".rstrip(":")])
    if cfg_judges.get("protocol") == "single-judge-v1":
        model = cfg_judges["j1_model"]
        try:
            rec = judge_mod.ask_vote(
                model, ctx, slot=1, seed=None,
                temperature=cfg_judges.get("temperature", 0.0),
                max_tokens=cfg_judges.get("max_tokens", 1500),
                max_context_chars=cfg_judges.get("max_context_chars", 12000),
                caller="service/single")
        except Exception as exc:  # noqa: BLE001
            return ("UNKNOWN", [], usage, True,
                    [f"channel_error:{model}:{type(exc).__name__}"])
        usage["calls"] = len(rec.get("attempts", []))
        ctx.judge_trace.append(rec)
        usage["api_calls"] = sum(not a.get("cached") for a in rec.get("attempts", []))
        usage["api_tokens"] = sum(int((a.get("usage") or {}).get("total_tokens") or 0)
                                  for a in rec.get("attempts", []) if not a.get("cached"))
        usage.update({k: int((rec.get("usage") or {}).get(k) or 0)
                      for k in ("prompt_tokens", "completion_tokens")})
        usage["tokens"] = int((rec.get("usage") or {}).get("total_tokens") or 0)
        if not rec.get("valid"):
            return ("UNKNOWN", [], usage, True,
                    ["single_judge_invalid_after_reask"])
        if rec["vote"]["label"] == 0:
            return ("NO_ERROR", [], usage, False, [])
        findings = _judge_findings([rec], ctx)
        if not findings:
            return ("UNKNOWN", [], usage, True,
                    ["positive_vote_without_finding"])
        return ("ERROR", findings, usage, False, [])
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
        ctx.judge_trace.append(rec)
        usage["api_calls"] = usage.get("api_calls", 0) + sum(
            not a.get("cached") for a in rec.get("attempts", []))
        usage["api_tokens"] = usage.get("api_tokens", 0) + sum(
            int((a.get("usage") or {}).get("total_tokens") or 0)
            for a in rec.get("attempts", []) if not a.get("cached"))

    v1, v2 = votes[0], votes[1]
    if v1["valid"] and v2["valid"] and v1["vote"]["label"] == v2["vote"]["label"]:
        label = v1["vote"]["label"]
        if label == 1:
            return ("ERROR", _judge_findings([v1, v2], ctx), usage, False, [])
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
    ctx.judge_trace.append(rec3)
    usage["api_calls"] = usage.get("api_calls", 0) + sum(
        not a.get("cached") for a in rec3.get("attempts", []))
    usage["api_tokens"] = usage.get("api_tokens", 0) + sum(
        int((a.get("usage") or {}).get("total_tokens") or 0)
        for a in rec3.get("attempts", []) if not a.get("cached"))
    u3 = rec3.get("usage") or {}
    usage["tokens"] += int(u3.get("total_tokens") or 0)
    usage["prompt_tokens"] += int(u3.get("prompt_tokens") or 0)
    usage["completion_tokens"] += int(u3.get("completion_tokens") or 0)
    if rec3["valid"]:
        label = rec3["vote"]["label"]
        if label == 1:
            return ("ERROR", _judge_findings([rec3], ctx), usage, False,
                    ["third_checker_decided"])
        return ("NO_ERROR", [], usage, False, ["third_checker_decided"])
    return ("UNKNOWN", [], usage, True,
            ["third_checker_invalid_after_reask"])


def _judge_findings(vote_records: list, ctx=None) -> list:
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
        if ctx is not None:
            source_texts = {"response": ctx.response_raw,
                            "policy": ctx.policy_text,
                            "history": ctx.prompt_raw,
                            "catalog": ctx.system}
            for quote in quotes:
                start = source_texts[quote["source"]].find(quote["text"])
                if start >= 0:
                    quote.update({"start": start,
                                  "end": start + len(quote["text"])})
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
        self._formal_records: dict[str, dict] = {}
        self._judge_replays: dict[str, dict] = {}
        replay_cfg = self.config.get("stages", {}).get("judge_replay")
        if replay_cfg:
            source = Path(replay_cfg["results_file"])
            if not source.is_absolute():
                source = REPO / source
            if hashlib.sha256(source.read_bytes()).hexdigest() != replay_cfg["sha256"]:
                raise ValueError("judge replay hash mismatch")
            for line in source.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                if (rec["id"] in self._judge_replays or
                        rec["source_config"] != replay_cfg["source_config"] or
                        rec["source_run_id"] != replay_cfg["source_run_id"]):
                    raise ValueError("judge replay identity mismatch")
                self._judge_replays[rec["id"]] = rec
        formal = self.config.get("stages", {}).get("formal_advisory")
        if formal:
            source = Path(formal["results_file"])
            if not source.is_absolute():
                source = REPO / source
            if hashlib.sha256(source.read_bytes()).hexdigest() != formal["sha256"]:
                raise ValueError("frozen formal results hash mismatch")
            status = json.loads((source.parent / "status.json").read_text(
                encoding="utf-8"))
            if (status["state"] != "SUCCEEDED" or
                    status["run_id"] != formal["run_id"]):
                raise ValueError("frozen formal run is incomplete or mismatched")
            for line in source.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                case_id = record["id"]
                if record["run_id"] != formal["run_id"] or case_id in self._formal_records:
                    raise ValueError("invalid frozen formal journal")
                self._formal_records[case_id] = record

    # -------------------------------------------------------------- helpers

    def channel_status(self) -> dict:
        """Cached, non-inference backend probe for /ready.

        Credential presence is reported separately from reachability; GET
        /models never generates a model answer. Probes occur only when /ready
        is requested and are cached for 60 seconds.
        """
        status = {"structural": True, "parser": True}
        self.channel_details = {}
        if self.config.get("stages", {}).get("source_search"):
            from guardian_truth.source_search.transport import ModelTransport
            if not hasattr(self, "_source_transport"):
                self._source_transport = ModelTransport(
                    Path("/workspace/guardian/results/source-search-api-phase-20261002"),
                    **self.config.get("model_budget", {}))
            configured = bool(self._source_transport.key and self._source_transport.model)
            status["source_model"] = configured
            self.channel_details["source_model"] = {"configured": configured,
                "reachable": None, "provider_availability": "UNPROBED",
                "probe_scope": "CREDENTIAL_PRESENCE_NOT_INFERENCE"}
        judges = self.config.get("stages", {}).get("judges")
        if judges:
            try:
                from llm import (MODEL_REGISTRY, PROVIDERS,  # noqa: PLC0415
                                 GRANITE_LOCAL_PATH)
                slots = (("j1_model",) if judges.get("protocol") ==
                         "single-judge-v1" else
                         ("j1_model", "j2_model", "third_model"))
                models = {judges[k] for k in slots}
                reviewer = self.config.get("stages", {}).get("counterevidence")
                if reviewer:
                    models.add(reviewer.get("resolved_model", reviewer["model"]))
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
                                  "reachable": ok, "reason": reason,
                                  "probe_scope": "GET_models_not_generation"}
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
        trace_id = case.get("_trace_id") or new_trace_id()
        case_id = str(case.get("case_id") or "unnamed")
        prompt = case.get("prompt") or ""
        response = case.get("response") or ""

        budget = int(self.limits.get("max_input_chars", 2000000))
        if len(prompt) + len(response) > budget:
            return self._finish(case_id, "UNKNOWN", "schema", [], [],
                {"structural": "not_run", "reason": "context_budget_exceeded",
                 "input_chars": len(prompt) + len(response), "budget": budget,
                 "limit_scope": "INPUT_ADMISSION_NOT_MODEL_WINDOW"},
                True, trace_id, {"calls": 0, "tokens": 0}, t0)

        ctx = parse_case_v02(case_id, prompt, response)
        findings = structural_findings(ctx)
        usage = {"calls": 0, "tokens": 0}

        source_search = self.config.get("stages", {}).get("source_search")
        if source_search:
            from guardian_truth.source_search.pipeline import run
            from guardian_truth.source_search.id_contract import run_ids
            from guardian_truth.source_search.transport import ModelTransport
            from guardian_truth.source_search.archive import persist_snapshot
            if findings:
                from guardian_truth.source_search import SourceStore
                store = SourceStore({"prompt": prompt, "response": response})
                archive = persist_snapshot(store.snapshot(),
                    (self.audit_path.parent if self.audit_path else
                     Path("/workspace/guardian/results/source_search_20261002/service")) / "source_stores")
                payload = self._finish(case_id, "ERROR", "schema", findings, suspicion_notes(ctx),
                    {"structural": "confirmed_hit", "source_index_complete": True,
                     "source_archive": archive, "semantic_completeness_proven": False},
                    False, trace_id, usage, t0)
                payload["source_store"] = store.snapshot()
                return payload
            if not hasattr(self, "_source_transport"):
                self._source_transport = ModelTransport(
                    Path("/workspace/guardian/results/source-search-api-phase-20261002"),
                    **self.config.get("model_budget", {}))
            before = self._source_transport.snapshot()
            interface = source_search.get("interface", "quotes")
            if interface not in ("quotes", "source_ids"):
                raise ValueError("unsupported source investigation interface")
            runner = run_ids if interface == "source_ids" else run
            options = {k:v for k,v in source_search.items() if k != "interface"}
            result = runner({"id": case_id, "prompt": prompt, "response": response},
                            self._source_transport, **options)
            archive = persist_snapshot(result["sources"],
                (self.audit_path.parent if self.audit_path else
                 Path("/workspace/guardian/results/source_search_20261002/service")) / "source_stores")
            after = self._source_transport.snapshot()
            usage = {"calls": after["actual_api_attempts"] - before["actual_api_attempts"],
                "tokens": after["known_provider_tokens"] - before["known_provider_tokens"],
                "unknown_usage_upper_bounds": after["unknown_usage_upper_bounds"] - before["unknown_usage_upper_bounds"]}
            assessment = result.get("assessment") or {}
            payload = self._finish(case_id, result["decision"], result["decision_basis"],
                assessment.get("findings", []), [],
                {**result["coverage"], "structural": "clean_scan",
                 "stop_reason": result["stop_reason"],
                 "source_archive": archive,
                 "open_questions": assessment.get("open_questions", list(result["material_query_gaps"]))},
                result["degraded"], trace_id, usage, t0,
                module_trace=result["trace"])
            # Returned archive is the same source store used for decisions, not
            # a second independently filtered representation.
            payload["source_store"] = result["sources"]
            return payload

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
                model_budget = int(self.limits.get("max_context_chars", 200000))
                if len(prompt) + len(response) > model_budget:
                    return self._finish(case_id, "UNKNOWN", "model", [], suspicion_notes(ctx),
                        {"structural": "clean_scan", "reason": "model_context_budget_exceeded",
                         "input_chars": len(prompt) + len(response), "model_budget": model_budget},
                        True, trace_id, usage, t0)
                advisory_kind = self.config.get("stages", {}).get(
                    "advisory", "none")
                try:
                    from modular_helpers import advisory_for  # noqa: PLC0415
                    ctx.advisory_context, advisory_coverage = advisory_for(
                        ctx, advisory_kind)
                    if self.config.get("stages", {}).get("formal_advisory"):
                        from modular_helpers import formal_advisory  # noqa: PLC0415
                        record = self._formal_records.get(case_id)
                        fingerprint = hashlib.sha256((prompt + "\x00" + response)
                                                     .encode("utf-8")).hexdigest()
                        if record is not None and record.get("source_sha256") != fingerprint:
                            formal_text = ""
                            formal_coverage = {"formal": "SOURCE_MISMATCH"}
                        else:
                            formal_text, formal_coverage = formal_advisory(record)
                        if formal_text:
                            ctx.advisory_context += "\n" + formal_text
                        advisory_coverage["formal"] = formal_coverage
                except Exception as exc:  # noqa: BLE001
                    return self._finish(
                        case_id, "UNKNOWN", "schema", findings,
                        suspicion_notes(ctx),
                        {"structural": "clean_scan",
                         "advisory": advisory_kind,
                         "reason": f"advisory_error:{type(exc).__name__}"},
                        True, trace_id, usage, t0)
                replay = self._judge_replays.get(case_id)
                fingerprint = hashlib.sha256((prompt + "\x00" + response).encode("utf-8")).hexdigest()
                if replay is not None and replay["source_sha256"] == fingerprint:
                    decision, jf = replay["decision"], replay["findings"]
                    degraded, reasons = replay["degraded"], []
                    usage = {"calls": 0, "tokens": 0, "api_calls": 0, "api_tokens": 0,
                             "replayed_calls": int(replay["usage"].get("calls") or 0),
                             "replayed_tokens": int(replay["usage"].get("tokens") or 0)}
                    ctx.judge_trace = [{"status": "FROZEN_BASELINE_REPLAY",
                                        "source_config": replay["source_config"],
                                        "source_run_id": replay["source_run_id"],
                                        "source_sha256": fingerprint,
                                        "original_decision": decision}]
                else:
                    decision, jf, usage, degraded, reasons = _judge_stage(judges, ctx)
                findings.extend(jf)
                trace = [{"module": "judge", "records": getattr(ctx, "judge_trace", [])}]
                review_cfg = self.config.get("stages", {}).get("counterevidence")
                review_coverage = None
                if review_cfg and (review_cfg["routing"] == "always" or
                                   decision != "NO_ERROR"):
                    try:
                        native = self.config.get("stages", {}).get("native_advisory")
                        if native:
                            from native_helper import native_advisory
                            try:
                                native_text, native_record = native_advisory(native, ctx)
                                if native_text:
                                    ctx.advisory_context += "\n" + native_text
                                trace.append(native_record)
                            except Exception as exc:
                                trace.append({"module": "native-advisory/1", "status": "UNAVAILABLE",
                                              "reason": type(exc).__name__})
                        from counterevidence import collect_review, aggregate_review
                        review = collect_review(review_cfg, ctx, findings)
                        original = decision
                        decision, findings, review_reason = aggregate_review(
                            review, original, findings, ctx)
                        usage = {key: int(usage.get(key) or 0) + int(
                            review["usage"].get(key) or 0)
                            for key in set(usage) | set(review["usage"])}
                        trace.append(review)
                        review_coverage = {"status": review["status"],
                                           "original_decision": original,
                                           "reason": review_reason}
                        degraded = degraded or not review["valid"]
                    except Exception as exc:  # noqa: BLE001
                        review_coverage = {"status": "UNAVAILABLE",
                                           "reason": type(exc).__name__,
                                           "fallback": "preserve_baseline"}
                        degraded = True
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
                coverage["advisory"] = advisory_coverage
                if review_coverage is not None:
                    coverage["counterevidence"] = review_coverage
                return self._finish(case_id, decision, basis, findings,
                                    suspicion_notes(ctx), coverage,
                                    bool(degraded), trace_id, usage, t0,
                                    module_trace=trace)

        return self._finish(case_id, decision, basis, findings,
                            suspicion_notes(ctx), coverage, False,
                            trace_id, usage, t0)

    def _finish(self, case_id, decision, basis, findings, assumptions,
                coverage, degraded, trace_id, usage, t0, module_trace=None) -> dict:
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
            "module_trace": module_trace or [],
        }
        if self.audit_path is not None:
            audit = audit_record(
                trace_id, self.config_id, case_id, decision, basis,
                len(findings), usage, degraded,
                [f.get("type", "") for f in findings],
                time.time() - t0)
            audit.update({"finding_details": findings,
                          "module_trace": module_trace or [],
                          "coverage": coverage, "assumptions": assumptions})
            written = append_jsonl(self.audit_path, audit)
            payload["audit_status"] = "WRITTEN" if written else "WRITE_FAILED"
            if not written:
                payload["degraded"] = True
                payload["coverage"] = dict(coverage, audit="WRITE_FAILED")
        else:
            payload["audit_status"] = "DISABLED"
        return payload

#!/usr/bin/env python3
"""Minimal competition adapter: run the frozen B4h-sound-v2 pipeline on raw
competition rows (prompt, response) from valid.parquet.

Directive sections 15/17: the adapter is TRANSPORT-ONLY. It splits the raw
prompt into the E2E field structure deterministically and fills every
research-only slot with its honest absent value:

  system_policy   <- the ⟦SYSTEM⟧ block (verbatim: instructions + policy +
                     [AVAILABLE TOOLS] catalog)
  user_request    <- concatenation of ALL ⟦USER⟧ turn bodies in order
                     (goal firewall source; the single-request research
                     convention does not hold for multi-turn real cases)
  history         <- the ⟦ASSISTANT⟧ / ⟦ASSISTANT · ход N⟧ blocks verbatim
                     (embedded → TOOL_CALL / ← TOOL_RESPONSE lines included;
                     the shared marker transport parses both spellings)
  target_response <- the raw response field (verbatim)
  tool_metadata / tool_schemas <- tool NAMES parsed from [AVAILABLE TOOLS]
                     (name-only dicts: exactly the shape the research corpus
                     used; no invented provider/version/schema hashes)
  t1_contracts    <- () (absent: no manually authored T1 in competition mode)
  state_contract  <- None (absent: no trusted current field values)
  history_complete<- False (absent: the competition input carries no
                     completeness statement; absence proofs stay blocked)
  authoritative_* <- () (oracle substitutions are research-only)

Missing information -> abstention, never an invented premise.

Modes:
  R1  competition prompt only, live LLM backend (provider from
      REAL_VALID_PROVIDER, default mistral) with a persisted content-addressed
      cache so reruns replay exactly.
  R2  structural only: a backend whose every proposal fails at transport;
      the deterministic layers (marker transport, ledger, catalog, claims
      gating, world composition, certificate) still run.

GOLD FIREWALL: this script reads ONLY id/prompt/response from the parquet.
Labels and explanations are joined by scripts/score_real_valid.py AFTER the
prediction files are sealed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from guardian_truth.vnext.adapters import AdapterMode  # noqa: E402
from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1  # noqa: E402
from guardian_truth.vnext.e2e.e2e_types_v1 import (E2EArmConfig, E2ECaseInput,  # noqa: E402
                                                   SEMANTICS_ARMS)
from guardian_truth.vnext.e2e.experiment_v1 import registry_for  # noqa: E402
from guardian_truth.vnext.semantic import Proposal  # noqa: E402

MARKER_SPLIT = re.compile(r'⟦(SYSTEM|USER|ASSISTANT(?:\s*·\s*ход\s*\d+)?)⟧[^\S\n]*\n?')
TOOL_DEF = re.compile(r'^- (?P<name>[\w.-]+)\s+[—–]\s*', re.MULTILINE)
ADAPTER_VERSION = "competition_real_adapter_v1"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_competition_prompt(prompt: str) -> dict:
    """Deterministic lossless split of a raw competition prompt.

    Returns {system, user_texts, history_events, leading_text, marker_count}.
    No LLM, no inference; every piece is a verbatim slice of the input.
    """
    markers = list(MARKER_SPLIT.finditer(prompt))
    leading_text = prompt[:markers[0].start()] if markers else prompt
    system_parts, user_texts, history_events = [], [], []
    for i, marker in enumerate(markers):
        tag = marker.group(1)
        start = marker.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(prompt)
        block = prompt[marker.start():end]
        if tag == "SYSTEM":
            system_parts.append(block[len(marker.group(0)):])
        elif tag == "USER":
            user_texts.append(block[len(marker.group(0)):].strip("\n"))
        else:                                   # ASSISTANT / ASSISTANT · ход N
            history_events.append(block.rstrip("\n"))
    return {"system": "\n".join(system_parts).strip("\n"),
            "user_texts": user_texts,
            "history_events": history_events,
            "leading_text": leading_text,
            "marker_count": len(markers)}


def catalog_tool_names(system_text: str) -> list[str]:
    """Tool NAMES from the [AVAILABLE TOOLS] catalog (deterministic)."""
    index = system_text.find("[AVAILABLE TOOLS]")
    if index < 0:
        return []
    return sorted(set(TOOL_DEF.findall(system_text[index:])))


def build_case(row_id: str, prompt: str, response: str) -> tuple[E2ECaseInput, dict]:
    """{id, prompt, response} -> E2ECaseInput + deterministic split report."""
    split = parse_competition_prompt(prompt)
    tools = catalog_tool_names(split["system"])
    case = E2ECaseInput(
        case_id=row_id,
        family="competition_real",
        system_policy=split["system"],
        user_request="\n\n".join(split["user_texts"]).strip("\n"),
        history=tuple(split["history_events"]),
        target_response=response,
        tool_metadata=tuple({"name": name} for name in tools),
        tool_schemas=tuple({"name": name} for name in tools),
        t1_contracts=(),
        state_contract=None,
        history_complete=False,
        completeness_basis="absent: competition input carries no completeness statement",
        authoritative_policy_readings=(),
        authoritative_goal_readings=(),
        authoritative_policy_behaviors=(),
        authoritative_goal_behaviors=(),
        gold_core_status="",
        gold_binary=None,
        notes="minimal competition adapter: prompt+response only; no research metadata")
    report = {"adapter_version": ADAPTER_VERSION,
              "system_chars": len(split["system"]),
              "user_turns": len(split["user_texts"]),
              "user_chars": len("\n\n".join(split["user_texts"])),
              "history_events": len(split["history_events"]),
              "catalog_tools": tools,
              "leading_text_chars": len(split["leading_text"].strip()),
              "marker_count": split["marker_count"]}
    return case, report


def build_r1_backend(cache_path: Path):
    """Live semantic backend through Guardian's own ChatClient.

    Provider is selectable via REAL_VALID_PROVIDER (default mistral); the
    frozen BAI/qwen3.8-flash endpoint was unreachable from this environment
    (recorded in the journal). All proposals persist to a content-addressed
    cache so the run is exactly reproducible.

    Transport shim: the mistral endpoint rejects the top-level
    `reasoning_effort` request field for ministral-14b-latest (HTTP 400,
    code 3051), which the frozen BAI endpoint accepted. The shim drops that
    single transport field at the HTTP-payload level only; task content,
    schema, temperature and token limits are unchanged (reasoning_effort is
    a thinking-budget knob, not task semantics).
    """
    from guardian_truth.llm_client import ChatClient, ClientConfig
    from guardian_truth.runtime import provider_config
    from guardian_truth.vnext.e2e.backend_v1 import E2ECachingBackend
    from guardian_truth.vnext.e2e.json_extract_backend_v1 import JsonExtractBackend

    class MistralCompatibleClient:
        def __init__(self, inner):
            self.inner = inner

        def validate_configuration(self):
            return self.inner.validate_configuration()

        def complete(self, messages, *, schema=None, budget=None, reasoning_effort=None):
            return self.inner.complete(messages, schema=schema, budget=budget)

    provider = os.environ.get("REAL_VALID_PROVIDER", "mistral")
    config = provider_config(ClientConfig(response_format_mode="none",
                                          timeout_seconds=120.0,
                                          max_output_tokens=2048,
                                          max_retries=int(os.environ.get("REAL_VALID_MAX_RETRIES", "5"))), provider)
    client = ChatClient(config)
    client.validate_configuration()
    inner = JsonExtractBackend(MistralCompatibleClient(client),
                               interval_seconds=float(os.environ.get("REAL_VALID_INTERVAL", "1.2")))
    return E2ECachingBackend(inner, cache_path=cache_path)


class StructuralOnlyBackend:
    """R2 ablation backend: every semantic proposal fails at transport.

    Frontends degrade to their recorded TRANSPORT failures; the deterministic
    layers (marker transport, ledger, catalog, claims gating, world
    composition, certificate) still execute.
    """

    def propose(self, task, payload, schema):
        return Proposal(None, "ERROR", "NOT_EVALUATED", "structural_only_mode")

    @property
    def receipts(self):
        return []

    @property
    def live_calls(self):
        return 0


def run_case(case: E2ECaseInput, backend, adapter_mode: AdapterMode):
    """One B4h-sound-v2 analysis. A crashed case is UNRESOLVED, never a verdict."""
    arm = E2EArmConfig("B4h", ("h0_hist",), ("conservative",))
    guardian = GuardianE2EV1(backend, registry=registry_for(case), arm=arm,
                             max_worlds=4096, adapter_mode=adapter_mode,
                             semantics=SEMANTICS_ARMS["B3"],
                             goal_format_repair=os.environ.get("REAL_VALID_GOAL_REPAIR", "1") == "1")
    started = time.time()
    try:
        analysis = guardian.analyze_e2e_v1(case)
        return {"core_status": analysis.result.status.value,
                "binary": analysis.product_decision.binary_label,
                "used_fallback": analysis.product_decision.used_fallback,
                "certificate_valid": bool(analysis.result.certificate_check
                                          and analysis.result.certificate_check.valid)
                if analysis.result.certificate_check else None,
                "worlds": analysis.world_count,
                "required_worlds": analysis.required_worlds,
                "frontend_failures": [{"component": name, "kind": kind}
                                       for name, kind, _ in analysis.frontend_statuses],
                "policy_readings": len(analysis.policy_readings),
                "goal_contracts": len(analysis.goal_contracts),
                "component_summary": dict(analysis.component_summary),
                "diagnostics": {"primary": analysis.result.diagnostics.primary_reason.value
                                if analysis.result.diagnostics.primary_reason else None,
                                "contributing": [r.value for r in
                                                 analysis.result.diagnostics.contributing_reasons],
                                "missing_evidence": list(analysis.result.diagnostics.missing_evidence[:12])},
                "elapsed_s": round(time.time() - started, 2),
                "error": None}
    except Exception as error:  # defensive: crashed case = UNRESOLVED
        return {"core_status": "UNRESOLVED", "binary": None, "used_fallback": True,
                "certificate_valid": False, "worlds": 0, "required_worlds": 0,
                "frontend_failures": [], "policy_readings": 0, "goal_contracts": 0,
                "component_summary": {},
                "diagnostics": {"primary": "EXECUTION_ERROR", "contributing": [],
                                "missing_evidence": [f"{type(error).__name__}:{str(error)[:300]}"]},
                "elapsed_s": round(time.time() - started, 2),
                "error": f"{type(error).__name__}:{str(error)[:300]}"}


def load_rows(input_path: Path, limit: int | None, only: str | None) -> list[dict]:
    """GOLD FIREWALL: reads id/prompt/response ONLY."""
    import pandas as pd
    frame = pd.read_parquet(input_path, columns=["id", "prompt", "response"])
    rows = [{"id": str(row["id"]), "prompt": str(row["prompt"]), "response": str(row["response"])}
            for _, row in frame.iterrows()]
    if only:
        rows = [row for row in rows if row["id"] == only]
    if limit:
        rows = rows[:limit]
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["R1", "R2"], required=True)
    parser.add_argument("--input", default="valid.parquet")
    parser.add_argument("--out-dir", default="outputs/vnext/real_valid")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only", default=None, help="run a single case id (smoke test)")
    parser.add_argument("--adapter-mode", choices=["audit", "competition-required-binary"],
                        default="competition-required-binary")
    args = parser.parse_args()

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    progress_path = out_dir / f"{args.mode}_progress.jsonl"
    cache_path = out_dir / f"{args.mode}_llm_cache.json"

    rows = load_rows(ROOT / args.input, args.limit, args.only)
    done = {}
    if progress_path.exists():
        for line in progress_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                done[record["id"]] = record
    pending = [row for row in rows if row["id"] not in done]
    print(f"[{args.mode}] cases total={len(rows)} done={len(done)} pending={len(pending)}")

    if args.mode == "R1":
        backend = build_r1_backend(cache_path)
    else:
        backend = StructuralOnlyBackend()
    adapter_mode = (AdapterMode.COMPETITION if args.adapter_mode == "competition-required-binary"
                    else AdapterMode.AUDIT)

    for row in pending:
        case, split_report = build_case(row["id"], row["prompt"], row["response"])
        receipts_before = len(backend.receipts)
        result = run_case(case, backend, adapter_mode)
        record = {"id": row["id"],
                  "input": {"prompt_sha256": sha256_text(row["prompt"]),
                            "response_sha256": sha256_text(row["response"]),
                            "prompt_chars": len(row["prompt"]),
                            "response_chars": len(row["response"])},
                  "split": split_report,
                  "llm": {"receipts": len(backend.receipts) - receipts_before,
                          "live_calls": getattr(backend, "live_calls", 0)},
                  args.mode: result,
                  "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        with open(progress_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{args.mode}] {row['id']}: {result['core_status']} binary={result['binary']} "
              f"cert={result['certificate_valid']} worlds={result['worlds']} "
              f"elapsed={result['elapsed_s']}s llm={record['llm']['receipts']}"
              + (f" ERROR={result['error']}" if result["error"] else ""), flush=True)
        if getattr(backend, "cache_path", None) is not None:
            backend._persist()

    if getattr(backend, "receipts", None) is not None:
        receipts_path = out_dir / f"{args.mode}_receipts.json"
        receipts_path.write_text(json.dumps(backend.receipts, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
        failed = [r for r in backend.receipts if r.get("transport_status") != "SUCCESS"
                  or (r.get("cache_hit") is False and r.get("transport_status") == "SUCCESS")]
        print(f"[{args.mode}] receipts={len(backend.receipts)} "
              f"(invalid-schema live: {sum(1 for r in backend.receipts if not r.get('cache_hit') and r.get('transport_status') == 'SUCCESS' and r.get('schema_status') != 'VALID')}) "
              f"-> {receipts_path}")

    print(f"[{args.mode}] complete: {progress_path}")


if __name__ == "__main__":
    main()

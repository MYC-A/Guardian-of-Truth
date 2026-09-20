#!/usr/bin/env python3
"""IFC suspicions runner — independent-fullcycle direction A (postfix: ifc).

Provider-agnostic OpenAI-compatible LLM runner implementing:
  s1_direct   — structured judge (A0-analog).
  s2_grounded — atomic suspicions with strict source-span grounding + repair loop
                (generalized repair of the A1 grounding producer: instead of
                trusting the producer, unanchored spans get an explicit repair
                feedback round and are re-gated; label=1 requires >=1 ANCHORED
                suspicion).
  s3_verified — s2 + independent cross-model verification of every anchored
                suspicion against the original context (A3-analog); label=1
                requires >=1 CONFIRMED verdict from the verifier model.

Gold-blind: reads only id,prompt,response. Append-only records.jsonl, resumable.
Never prints or stores API keys.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------- providers

PROVIDERS = {
    "blockrun": {
        "base_url": "https://blockrun.ai/api/v1",
        "model": "nvidia/gpt-oss-120b",
        "api_key": "not-needed",
        "min_interval": 0.0,
        "key_env": None,
    },
    "pollinations": {
        "base_url": "https://text.pollinations.ai/openai",
        "model": "openai-fast",
        "api_key": "not-needed",
        "min_interval": 15.0,
        "key_env": None,
    },
    "llm7": {
        "base_url": "https://api.llm7.io/v1",
        "model": "fast",
        "api_key": "unused",
        "min_interval": 6.5,
        "key_env": None,
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "model": None,  # resolved at call time: env MISTRAL_MODEL or default
        "api_key": None,  # resolved at call time from env MISTRAL_API_KEY
        "min_interval": 0.5,
        "key_env": "MISTRAL_API_KEY",
        "default_model": "ministral-14b-latest",
    },
}


class LLM:
    """Minimal OpenAI-compatible chat client with per-provider pacing + retries."""

    def __init__(self, provider: str, timeout: int = 180, max_retries: int = 2):
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider {provider}")
        self.name = provider
        spec = dict(PROVIDERS[provider])
        if spec["key_env"]:
            key = os.environ.get(spec["key_env"], "").strip()
            if not key:
                raise RuntimeError(f"provider {provider} requires env {spec['key_env']}")
            spec["api_key"] = key
            spec["model"] = os.environ.get("MISTRAL_MODEL", spec.get("default_model") or "mistral-small-latest")
        self.base_url = spec["base_url"].rstrip("/")
        self.requested_model = spec["model"]
        self.api_key = spec["api_key"]
        self.min_interval = spec["min_interval"]
        self.timeout = timeout
        self.max_retries = max_retries
        self._last_call = 0.0
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def chat(self, messages: list[dict], max_tokens: int = 1024, temperature: float = 0.0) -> dict:
        wait = self.min_interval - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        payload = {
            "model": self.requested_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        last_err = None
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            )
            try:
                t0 = time.time()
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode())
                self._last_call = time.time()
                self.calls += 1
                usage = data.get("usage") or {}
                self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
                self.completion_tokens += int(usage.get("completion_tokens") or 0)
                return {
                    "content": (data["choices"][0]["message"] or {}).get("content") or "",
                    "actual_model": data.get("model", self.requested_model),
                    "latency_s": round(time.time() - t0, 2),
                    "usage": usage,
                }
            except urllib.error.HTTPError as e:
                body = b""
                try:
                    body = e.read()
                except Exception:  # noqa: BLE001
                    pass
                last_err = f"HTTP {e.code}: {body[:200]!r}"
                if e.code in (429, 500, 502, 503):
                    wait_s = 0.0
                    try:
                        err_json = json.loads(body.decode())
                        wait_s = float(err_json.get("retry_after") or err_json.get("error", {}).get("retry_after") or 0)
                    except Exception:  # noqa: BLE001
                        pass
                    if e.code == 429 and wait_s == 0.0:
                        wait_s = 30.0  # conservative for keyless pools with token quotas
                    time.sleep(min(120.0, max(wait_s, (2 ** attempt) * 5.0)))
                    continue
                break
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {str(e)[:200]}"
                time.sleep(min(30.0, (2 ** attempt) * 3.0))
        raise RuntimeError(f"LLM {self.name} failed after retries: {last_err}")


# ---------------------------------------------------------------- json utils

def extract_json(text: str):
    """Best-effort JSON extraction from a model reply."""
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


# ---------------------------------------------------------------- span gate

def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def find_span(document: str, evidence: dict) -> dict:
    """Anchor evidence to a document. Returns {status, issue, start, end, mode}.

    Protocol: the MODEL quotes verbatim, the SYSTEM anchors offsets by exact
    search (model-quotes/system-anchors). Model-supplied offsets are honored
    only when they match exactly. Whitespace-normalized matching is a fallback
    (long verbatim quotes across line breaks). Offsets: zero-based code points.
    """
    quote = (evidence.get("quote") or "").strip()
    if not quote:
        return {"status": "UNANCHORED", "issue": "source_quote_not_found"}
    if evidence.get("document") not in ("prompt", "response"):
        return {"status": "UNANCHORED", "issue": "source_document_invalid"}
    start, end = evidence.get("start"), evidence.get("end")
    if isinstance(start, int) and isinstance(end, int) and 0 <= start <= end <= len(document):
        if document[start:end] == quote:
            return {"status": "ANCHORED", "issue": None, "start": start, "end": end, "mode": "model_offsets"}
    occurrences = [m.start() for m in re.finditer(re.escape(quote), document)]
    if len(occurrences) == 1:
        return {"status": "ANCHORED", "issue": None, "start": occurrences[0],
                "end": occurrences[0] + len(quote), "mode": "system_anchored"}
    if len(occurrences) > 1:
        return {"status": "UNANCHORED", "issue": "source_quote_ambiguous"}
    # whitespace-normalized fallback
    n_doc, n_quote = _norm_ws(document), _norm_ws(quote)
    n_occ = [m.start() for m in re.finditer(re.escape(n_quote), n_doc)]
    if len(n_occ) == 1:
        return {"status": "ANCHORED", "issue": None, "start": -1, "end": -1, "mode": "system_anchored_normalized"}
    if len(n_occ) > 1:
        return {"status": "UNANCHORED", "issue": "source_quote_ambiguous"}
    return {"status": "UNANCHORED", "issue": "source_quote_not_found"}


GATE_ISSUE_HINT = {
    "source_quote_offset_mismatch": "quote exists but start/end offsets do not match it (offsets are zero-based code-point indices)",
    "source_offsets_out_of_bounds": "start/end offsets are outside the document",
    "source_quote_not_found": "quote text not found verbatim in the document (copy it exactly)",
    "source_quote_ambiguous": "quote occurs multiple times; extend it to be unique",
    "source_document_invalid": "document must be exactly 'prompt' or 'response'",
}


# ---------------------------------------------------------------- prompts

S2_SYSTEM = """You are a forensic auditor of agent trajectories. You receive a full context
(SYSTEM/POLICY, USER/ASSISTANT history, tool schemas, tool calls, tool results) and the
target ASSISTANT response. Your job: detect CONTEXT ERRORS in the response — claims or
actions contradicted by the provided facts, unmet policy requirements, wrong tool
arguments, stale state, wrong attribution, or violated explicit constraints.

Output STRICT JSON only:
{"suspicions": [
  {"claim": "<one verifiable claim/action from the response>",
   "error_type": "<one of: contradiction_with_facts|unverified_success|wrong_tool_result_use|wrong_tool_arguments|policy_violation|stale_state|wrong_attribution|lost_condition>",
   "score": <0.0-1.0 confidence this is a real error>,
   "evidence": {"document": "<prompt|response>", "quote": "<EXACT verbatim substring copied character-for-character from that document>"},
   "note": "<why this quote matters>"}
]}

Rules:
- Up to 5 suspicions; only REAL discrepancies, not style issues.
- quote MUST be copied VERBATIM (character-for-character) from prompt or response.
  Do NOT compute offsets — exact quoting is enough; the system anchors positions.
- If the response is consistent with the context and policy, output an empty list.
- JSON only — no prose, no markdown fences."""

REPAIR_SYSTEM = """You must fix invalid evidence spans. You get one suspicion JSON and the
gate failure reason. Re-emit ONLY this JSON object with corrected evidence:
{"document": "<prompt|response>", "quote": "<EXACT verbatim substring copied character-for-character from that document>"}
Do NOT compute offsets. Copy the quote exactly as it appears (no paraphrase, no added spaces).
If the quote appears multiple times, extend it with surrounding words until unique.
JSON only."""

VERIFY_SYSTEM = """You are an independent fact checker. You get the ORIGINAL full context
and one suspicion with an anchored quote. Verify ONLY against the original context:
does the context confirm this is a REAL error in the assistant response?
Output STRICT JSON: {"verdict": "<CONFIRMED|REFUTED|UNCERTAIN>", "reason": "<short>",
"basis_quote": "<optional exact quote from context>"}
CONFIRMED only if the original text itself proves the discrepancy. JSON only."""

S1_SYSTEM = """You are a judge of agent trajectories. Given full context and the target
ASSISTANT response, decide whether the response contains a CONTEXT ERROR (contradiction
with provided facts, unverified success claim, wrong tool use/arguments, violated explicit
policy constraint, stale state, wrong attribution). Do NOT flag style issues.
Output STRICT JSON: {"label": 0 or 1, "reason_type": "<type>", "reason": "<short>", "score": <0.0-1.0>}
JSON only."""


def context_block(prompt: str, response: str, max_chars: int) -> str:
    if len(prompt) + len(response) <= max_chars:
        return f"=== ORIGINAL CONTEXT (prompt) ===\n{prompt}\n\n=== TARGET RESPONSE ===\n{response}"
    marker = "\n[...TRUNCATED...]\n"
    budget = max_chars - 200
    p_keep, r_keep = int(budget * 0.55), budget - int(budget * 0.55)
    p = prompt if len(prompt) <= p_keep else prompt[: p_keep // 2] + marker + prompt[-p_keep // 2 :]
    r = response if len(response) <= r_keep else response[: r_keep // 2] + marker + response[-r_keep // 2 :]
    return f"=== ORIGINAL CONTEXT (prompt, truncated) ===\n{p}\n\n=== TARGET RESPONSE ===\n{r}"


# ---------------------------------------------------------------- variants

def run_s1(llm: LLM, case: dict, ctx: str, records: list) -> dict:
    reply = llm.chat(
        [{"role": "system", "content": S1_SYSTEM},
         {"role": "user", "content": f"{ctx}\n\nReturn the JSON verdict now."}],
        max_tokens=512,
    )
    parsed = extract_json(reply["content"]) or {}
    label = 1 if parsed.get("label") == 1 else 0
    return {
        "prediction": label,
        "parsed": parsed,
        "raw": reply["content"][:2000],
        "model_actual": reply["actual_model"],
        "latency_s": reply["latency_s"],
        "calls": 1,
    }


def run_s2(llm: LLM, case: dict, ctx: str, records: list, max_repair_rounds: int = 2) -> dict:
    documents = {"prompt": case["prompt"], "response": case["response"]}
    reply = llm.chat(
        [{"role": "system", "content": S2_SYSTEM},
         {"role": "user", "content": f"{ctx}\n\nReturn the suspicions JSON now."}],
        max_tokens=2048,
    )
    parsed = extract_json(reply["content"]) or {}
    suspicions = parsed.get("suspicions") if isinstance(parsed.get("suspicions"), list) else []
    gate_log, repair_calls = [], 0
    for idx, s in enumerate(suspicions[:5]):
        evidence = s.get("evidence") or {}
        doc_name = evidence.get("document")
        gate = find_span(documents.get(doc_name, ""), evidence)
        rounds = 0
        history = [{"role": "system", "content": REPAIR_SYSTEM},
                   {"role": "user", "content": f"Suspicion JSON:\n{json.dumps(s, ensure_ascii=False)}\n\n"
                    f"Gate failure: {gate['issue']} ({GATE_ISSUE_HINT.get(gate['issue'], 'unknown')}). "
                    f"Fix the evidence and re-emit the JSON."}]
        while gate["status"] == "UNANCHORED" and rounds < max_repair_rounds:
            try:
                rep = llm.chat(history, max_tokens=512)
                repair_calls += 1
                rep_json = extract_json(rep["content"])
                if isinstance(rep_json, dict) and "quote" in rep_json:
                    gate = find_span(documents.get(rep_json.get("document"), ""), rep_json)
                    evidence = rep_json if gate["status"] == "ANCHORED" else evidence
                    history.append({"role": "assistant", "content": rep["content"][:1500]})
                    history.append({"role": "user", "content": f"Still failing: {gate['issue']} ({GATE_ISSUE_HINT.get(gate['issue'], 'unknown')}). document MUST be exactly 'prompt' or 'response'. Try again."})
            except Exception as e:  # noqa: BLE001
                gate_log.append({"idx": idx, "repair_error": str(e)[:200]})
                break
            rounds += 1
        gate_log.append({"idx": idx, "issue": gate["issue"], "status": gate["status"], "repair_rounds": rounds})
        s["_gate"] = gate
        s["_evidence_final"] = evidence if gate["status"] == "ANCHORED" else None
    anchored = [s for s in suspicions if s.get("_gate", {}).get("status") == "ANCHORED"]
    prediction = 1 if anchored else 0
    return {
        "prediction": prediction,
        "n_suspicions": len(suspicions),
        "n_anchored": len(anchored),
        "anchored_prediction": prediction,
        "gate_log": gate_log,
        "suspicions": suspicions[:5],
        "raw": reply["content"][:2500],
        "model_actual": reply["actual_model"],
        "latency_s": reply["latency_s"],
        "calls": 1 + repair_calls,
    }


def run_s3(llm: LLM, verifier: LLM, case: dict, ctx: str, records: list) -> dict:
    s2 = run_s2(llm, case, ctx, records)
    verdicts = []
    confirmations = 0
    anchored = [s for s in s2.get("suspicions", []) if s.get("_gate", {}).get("status") == "ANCHORED"]
    for s in anchored:
        try:
            v = verifier.chat(
                [{"role": "system", "content": VERIFY_SYSTEM},
                 {"role": "user", "content": f"{ctx}\n\n=== SUSPICION TO VERIFY ===\n{json.dumps(s, ensure_ascii=False)}"}],
                max_tokens=512,
            )
            vj = extract_json(v["content"]) or {}
            verdict = vj.get("verdict", "UNCERTAIN")
            if verdict == "CONFIRMED":
                confirmations += 1
            verdicts.append({"verdict": verdict, "reason": str(vj.get("reason"))[:300], "model": v["actual_model"]})
        except Exception as e:  # noqa: BLE001
            verdicts.append({"verdict": "ERROR", "reason": str(e)[:200]})
    s2["verdicts"] = verdicts
    s2["n_confirmed"] = confirmations
    s2["prediction"] = 1 if confirmations > 0 else 0
    s2["calls"] = s2.get("calls", 1) + len(verdicts)
    return s2


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="CSV/parquet with id,prompt,response")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--variant", required=True, choices=["s1", "s2", "s3"])
    ap.add_argument("--producer", default="blockrun")
    ap.add_argument("--verifier", default="pollinations", help="s3 only")
    ap.add_argument("--max-rows", type=int, default=0)
    ap.add_argument("--max-input-chars", type=int, default=300000)
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    in_path = Path(args.input)
    if in_path.suffix == ".parquet":
        import pandas as pd
        df = pd.read_parquet(in_path)[["id", "prompt", "response"]]
    else:
        import csv
        csv.field_size_limit(min(2 ** 31 - 1, 2 ** 30))
        rows = list(csv.DictReader(open(in_path, encoding="utf-8")))
        df = pd.DataFrame(rows)[["id", "prompt", "response"]] if rows else []
    cases = df.to_dict("records")
    if args.max_rows:
        cases = cases[: args.max_rows]

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rec_path = out_dir / "records.jsonl"
    done = {}
    if rec_path.exists():
        for line in open(rec_path, encoding="utf-8"):
            try:
                rec = json.loads(line)
                done[rec["id"]] = not rec.get("error")  # True = completed OK
            except Exception:  # noqa: BLE001
                pass

    producer = LLM(args.producer, timeout=args.timeout)
    verifier = LLM(args.verifier, timeout=args.timeout) if args.variant == "s3" else None
    ds_sha = hashlib.sha256(in_path.read_bytes()).hexdigest()[:16]

    manifest = {
        "line": "independent-fullcycle-20260920",
        "postfix": "ifc",
        "hypothesis": {
            "s1": "A0-analog direct structured judge (high recall, FP-prone baseline)",
            "s2": "A1 generalized: suspicions + strict span gate + repair loop; label=1 iff >=1 ANCHORED",
            "s3": "A3-analog: s2 + independent cross-model verification; label=1 iff >=1 CONFIRMED",
        },
        "variant": args.variant, "producer": args.producer, "verifier": args.verifier,
        "producer_model_requested": producer.requested_model,
        "verifier_model_requested": verifier.requested_model if verifier else None,
        "git_sha": os.popen("git rev-parse HEAD").read().strip(),
        "dataset_sha256_16": ds_sha,
        "max_input_chars": args.max_input_chars,
        "n_cases": len(cases), "started_utc": datetime.now(UTC).isoformat(),
    }

    t_start = time.time()
    with open(rec_path, "a", encoding="utf-8") as fh:
        for i, case in enumerate(cases):
            if done.get(case["id"]):
                continue
            ctx = context_block(case["prompt"], case["response"], args.max_input_chars)
            rec = {"id": case["id"], "variant": args.variant, "producer": args.producer, "ts": datetime.now(UTC).isoformat()}
            try:
                if args.variant == "s1":
                    res = run_s1(producer, case, ctx, None)
                elif args.variant == "s2":
                    res = run_s2(producer, case, ctx, None)
                else:
                    res = run_s3(producer, verifier, case, ctx, None)
                rec.update(res)
                rec["error"] = None
            except Exception as e:  # noqa: BLE001
                rec.update({"prediction": None, "error": str(e)[:300]})
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            print(f"[{i+1}/{len(cases)}] {case['id']} -> {rec.get('prediction')} "
                  f"(anch={rec.get('n_anchored','-')} conf={rec.get('n_confirmed','-')} err={rec.get('error')})", flush=True)

    manifest["finished_utc"] = datetime.now(UTC).isoformat()
    manifest["wall_seconds"] = round(time.time() - t_start, 1)
    manifest["producer_calls"] = producer.calls
    manifest["producer_tokens"] = {"prompt": producer.prompt_tokens, "completion": producer.completion_tokens}
    if verifier:
        manifest["verifier_calls"] = verifier.calls
        manifest["verifier_tokens"] = {"prompt": verifier.prompt_tokens, "completion": verifier.completion_tokens}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("MANIFEST:", json.dumps(manifest)[:600])
    return 0


if __name__ == "__main__":
    sys.exit(main())

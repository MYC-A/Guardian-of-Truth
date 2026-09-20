#!/usr/bin/env python3
"""IFC dual-critic theory building — independent-fullcycle direction B (postfix: ifc).

Two INDEPENDENT generative critics extract semantic theories from the same policy,
critique each other with source-grounded issues, then repair their own theory.
Fixes the Codex failure mode (NuExtract declined 100% of repairs): both critics
are full generative models, repairs are mandatory-but-attributable decisions.

Per case (gold-blind):
  1. extract: critic_a, critic_b -> independent theories (strict JSON)
  2. registry: clause quotes from input.jsonl act as source anchors; coverage =
     which clause quote keywords each theory references
  3. mutual critique: A reviews B, B reviews A (issues with evidence quotes)
  4. repair: each critic receives issues against its OWN theory and must either
     fix (revised theory) or explicitly reject each issue with a reason
  5. record everything for post-hoc scoring against gold expectations.

Output: records.jsonl (append-only, resumable) + manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ifc_suspicions import LLM, extract_json  # reuse client + JSON utils

EXTRACT_SYSTEM = """You are a policy formalization specialist. Read the POLICY text and
extract a complete semantic theory. Preserve EVERY condition, exception, temporal
constraint, actor and modality. Do not invent requirements that are not in the text.

Output STRICT JSON:
{"rules": [
  {"actor": "<who>", "action": "<what>",
   "modality": "<MUST|MUST_NOT|MAY>",
   "conditions": ["<verbatim condition phrases from policy>"],
   "exceptions": ["<verbatim exception phrases from policy>"],
   "temporal": {"relation": "<BEFORE|AFTER|WITHIN_N|ON_DATE|null>", "detail": "<phrase>"},
   "scope": "<which orders/entities this applies to>",
   "anchor_quotes": ["<EXACT verbatim substrings from the policy proving this rule>"]}
]}

Rules:
- Extract ALL rules; one JSON rule per distinct normative requirement.
- anchor_quotes must be copied character-for-character from the POLICY text.
- JSON only."""

CRITIQUE_SYSTEM = """You are an independent policy-interpretation critic. You get the
ORIGINAL policy, your OWN theory (for reference), and ANOTHER model's theory of the same
policy. Find concrete semantic errors in the OTHER theory:
- missing_condition / missing_exception (present in policy, absent in theory)
- wrong_modality (MUST vs MAY vs MUST_NOT)
- invented_requirement (not in the policy text)
- wrong_scope (applies to wrong entity/order)
- wrong_temporal (before/after/date errors)
- wrong_actor

Output STRICT JSON:
{"issues": [
  {"target_rule_index": <int index into the OTHER theory's rules array>,
   "type": "<one of the types above>",
   "explanation": "<short>",
   "evidence_quote": "<EXACT verbatim policy substring proving the issue>"}
]}
If the other theory is faithful, output {"issues": []}. JSON only."""

REPAIR_SYSTEM = """You are revising your OWN policy theory after independent critique.
You get: the ORIGINAL policy, your theory, and a list of issues raised by a critic.
For each issue DECIDE: accept (fix the theory) or reject (keep yours, explain why).
Reject only if the policy text genuinely does not support the issue.

Output STRICT JSON:
{"decision": "<ACCEPTED|REJECTED|PARTIAL>",
 "revised_theory": <the FULL corrected theory JSON in the same schema as your original>,
 "per_issue": [{"index": <int>, "decision": "<accepted|rejected>", "reason": "<short>"}]}
JSON only."""


def policy_text(case: dict) -> str:
    return "\n".join(s.get("text", "") for s in case.get("sources", []))


def registry_coverage(case: dict, theory: dict) -> dict:
    """Proxy semantic coverage: for each policy clause quote, does the theory
    reference its key phrases? (keyword overlap on content words)"""
    blob = json.dumps(theory, ensure_ascii=False).lower()
    per_clause = []
    for cl in case.get("clauses", []):
        words = [w for w in re.findall(r"[a-z]{4,}", cl.get("quote", "").lower())
                 if w not in ("must", "shall", "with", "that", "this", "from", "into", "only", "when", "then", "before", "after", "your", "their", "have", "been", "without", "unless", "issue", "them")]
        hit = sum(1 for w in words if w in blob)
        per_clause.append({"clause_id": cl.get("clause_id"), "hits": hit, "of": len(words)})
    covered = sum(1 for p in per_clause if p["hits"] >= max(1, int(p["of"] * 0.4)))
    return {"per_clause": per_clause, "clauses": len(per_clause), "covered": covered}


def run_case(llm_a: LLM, llm_b: LLM, case: dict) -> dict:
    policy = policy_text(case)
    user_extract = f"=== POLICY ===\n{policy}\n\nReturn the theory JSON now."
    ta = llm_a.chat([{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": user_extract}], max_tokens=2048)
    tb = llm_b.chat([{"role": "system", "content": EXTRACT_SYSTEM}, {"role": "user", "content": user_extract}], max_tokens=2048)
    theory_a = extract_json(ta["content"]) or {}
    theory_b = extract_json(tb["content"]) or {}

    def critique(critic: LLM, own, other, own_name, other_name):
        try:
            r = critic.chat([
                {"role": "system", "content": CRITIQUE_SYSTEM},
                {"role": "user", "content": f"=== POLICY ===\n{policy}\n\n=== YOUR THEORY ({own_name}) ===\n{json.dumps(own, ensure_ascii=False)}\n\n=== OTHER THEORY ({other_name}) TO CRITIQUE ===\n{json.dumps(other, ensure_ascii=False)}\n\nReturn the issues JSON now."}],
                max_tokens=1200)
            return extract_json(r["content"]) or {"issues": []}, r
        except Exception as e:  # noqa: BLE001
            return {"issues": [], "error": str(e)[:200]}, None

    crit_a_on_b, ra1 = critique(llm_a, theory_a, theory_b, "A", "B")
    crit_b_on_a, ra2 = critique(llm_b, theory_b, theory_a, "B", "A")

    def repair(critic: LLM, own, issues):
        try:
            r = critic.chat([
                {"role": "system", "content": REPAIR_SYSTEM},
                {"role": "user", "content": f"=== POLICY ===\n{policy}\n\n=== YOUR THEORY ===\n{json.dumps(own, ensure_ascii=False)}\n\n=== ISSUES FROM CRITIC ===\n{json.dumps(issues, ensure_ascii=False)}\n\nReturn the decision JSON now."}],
                max_tokens=2500)
            return extract_json(r["content"]) or {}, r
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:200]}, None

    rep_a, _ = repair(llm_a, theory_a, crit_a_on_b.get("issues", []))
    rep_b, _ = repair(llm_b, theory_b, crit_b_on_a.get("issues", []))

    final_a = rep_a.get("revised_theory") if isinstance(rep_a.get("revised_theory"), dict) else theory_a
    final_b = rep_b.get("revised_theory") if isinstance(rep_b.get("revised_theory"), dict) else theory_b

    return {
        "theory_a": theory_a, "theory_b": theory_b,
        "critique_a_on_b": crit_a_on_b, "critique_b_on_a": crit_b_on_a,
        "repair_a_decision": rep_a.get("decision"), "repair_a_per_issue": rep_a.get("per_issue"),
        "repair_b_decision": rep_b.get("decision"), "repair_b_per_issue": rep_b.get("per_issue"),
        "theory_a_revised": rep_a.get("decision") == "ACCEPTED",
        "theory_b_revised": rep_b.get("decision") == "ACCEPTED",
        "final_a": final_a, "final_b": final_b,
        "coverage_a_initial": registry_coverage(case, theory_a),
        "coverage_b_initial": registry_coverage(case, theory_b),
        "coverage_a_final": registry_coverage(case, final_a),
        "coverage_b_final": registry_coverage(case, final_b),
        "model_a_actual": ta["actual_model"], "model_b_actual": tb["actual_model"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="theory_extraction_v1 input.jsonl")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--critic-a", default="blockrun")
    ap.add_argument("--critic-b", default="llm7")
    ap.add_argument("--max-rows", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()

    cases = [json.loads(l) for l in open(args.input, encoding="utf-8") if l.strip()]
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
                done[rec["case_id"]] = not rec.get("error")  # True = completed OK
            except Exception:  # noqa: BLE001
                pass

    llm_a = LLM(args.critic_a, timeout=args.timeout)
    llm_b = LLM(args.critic_b, timeout=args.timeout)
    manifest = {
        "line": "independent-fullcycle-20260920", "postfix": "ifc",
        "hypothesis": "Two independent generative critics + grounded mutual critique + mandatory repair decision improve theory fidelity vs single-extractor pipelines",
        "critic_a": args.critic_a, "critic_b": args.critic_b,
        "git_sha": os.popen("git rev-parse HEAD").read().strip(),
        "dataset_sha256_16": hashlib.sha256(Path(args.input).read_bytes()).hexdigest()[:16],
        "n_cases": len(cases), "started_utc": datetime.now(UTC).isoformat(),
    }
    t0 = time.time()
    with open(rec_path, "a", encoding="utf-8") as fh:
        for i, case in enumerate(cases):
            if done.get(case["case_id"]):
                continue
            rec = {"case_id": case["case_id"], "ts": datetime.now(UTC).isoformat()}
            try:
                rec.update(run_case(llm_a, llm_b, case))
                rec["error"] = None
            except Exception as e:  # noqa: BLE001
                rec["error"] = str(e)[:300]
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            print(f"[{i+1}/{len(cases)}] {case['case_id']} err={rec['error']}", flush=True)

    manifest["finished_utc"] = datetime.now(UTC).isoformat()
    manifest["wall_seconds"] = round(time.time() - t0, 1)
    manifest["calls_a"] = llm_a.calls
    manifest["calls_b"] = llm_b.calls
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("MANIFEST:", json.dumps(manifest)[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())

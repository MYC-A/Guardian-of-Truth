#!/usr/bin/env python3
"""V6 — PRE-REGISTERED two-family judges + third checker (frozen 2026-10-01
BEFORE any holdout inference; see PREREGISTERED_PROTOCOL.md).

Decision rule (equal family weight; repeats never vote):
  1. V0.1 structural confirmed hit -> label 1 (short-circuit, never
     overwritten).
  2. J1 = gemma4:31b greedy (family: gemma)
     J2 = mistral greedy     (family: mistral)
     - both votes valid AND equal -> label = agreed label
     - disagreement OR any invalid vote -> THIRD CHECKER
       T = granite-guardian-4.1-8b local greedy (family: granite)
       - T valid -> label = T's vote
       - T invalid -> label 0, row marked degraded (never a silent
         confident 0)
  3. Audit: routing reason per case (agreed | disagreement | invalid:<who>),
     every vote/attempt, structural status, atomic predictions writes.

A vote-validation failure ROUTES TO THE THIRD CHECKER (does not silently
become 0) — this fixes the citation-fallback FN class measured on public46.

Usage:
  python run_v6.py --input data/x.csv --outdir outputs/x_v6 \
      [--max-cases N]   # dev pilot limit
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (append_audit, case_audit_record, load_cases_csv,  # noqa
                    load_cases_parquet, parse_case, sha256_text,
                    structural_label, write_predictions)
from judge import ask_vote, DEFAULT_MAX_CONTEXT_CHARS  # noqa

J1_MODEL = "gemma4:31b"                # family: gemma
J2_MODEL = "ministral-14b-latest"      # family: mistral
T_MODEL = "gpt-oss:20b"              # family: gpt-oss (ollama.com)

PROTOCOL_VERSION = "V6-preregistered-2026-10-01"


def vote_summary(v):
    if v is None:
        return None
    return {"model": v["model"], "family": v["family"], "slot": v["slot"],
            "seed": v["seed"], "temperature": v["temperature"],
            "valid": v["valid"], "invalid_reason": v["invalid_reason"],
            "vote": v["vote"], "attempts": v["attempts"],
            "context_trim": v["context_trim"],
            "transport_error": v["transport_error"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--name", default="ta_v6")
    ap.add_argument("--max-cases", type=int, default=0,
                    help="dev pilot limit (0 = all)")
    ap.add_argument("--skip-third", action="store_true",
                    help="DIAGNOSTIC ONLY: never call the third checker "
                         "(degraded rows instead) — forbidden on real runs")
    args = ap.parse_args()

    inp, outdir = Path(args.input), Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    cases = (load_cases_parquet(inp) if inp.suffix == ".parquet"
             else load_cases_csv(inp))
    if args.max_cases:
        cases = cases[: args.max_cases]

    run_cfg = {
        "stage": "V6_two_judges_third_checker",
        "protocol": PROTOCOL_VERSION,
        "preregistration": "PREREGISTERED_PROTOCOL.md (frozen before any "
                           "holdout inference)",
        "input": str(inp), "rows": len(cases),
        "input_sha256": sha256_text(inp.read_text(errors="replace")),
        "judges": {"J1": J1_MODEL, "J2": J2_MODEL, "third": T_MODEL},
        "families": {"J1": "gemma", "J2": "mistral", "third": "gpt-oss"},
        "equal_family_weight": True,
        "repeats_vote": False,
        "validation_failure_routes_to_third": True,
        "structural_channel": "V0.1 (R1/R2 policy-gated + R3 subfields)",
        "max_context_chars": DEFAULT_MAX_CONTEXT_CHARS,
        "judge_prompt": "judge.JUDGE_SYSTEM v1 (frozen in repo)",
        "skip_third_flag_set": bool(args.skip_third),
        "timestamp": time.time(),
    }
    (outdir / "run_config.json").write_text(json.dumps(run_cfg, indent=2))

    rows, stats = [], {"structural_shortcut": 0, "agreed": 0,
                       "third_routed": 0, "degraded": 0}
    t0 = time.time()
    vpath = outdir / f"{args.name}_predictions.csv"
    for i, c in enumerate(cases):
        ctx = parse_case(c["id"], c["prompt"], c["response"])
        rec = case_audit_record(ctx, "V6")
        votes, dec = [], {"label": 0, "mode": "?", "degraded": False}
        if ctx.structural_hits:
            stats["structural_shortcut"] += 1
            dec = {"label": 1, "mode": "structural_confirmed",
                   "degraded": False, "structural": True}
        else:
            v1 = ask_vote(J1_MODEL, ctx, slot=1, seed=None,
                          temperature=0.0, caller="V6")
            v2 = ask_vote(J2_MODEL, ctx, slot=2, seed=None,
                          temperature=0.0, caller="V6")
            votes = [vote_summary(v1), vote_summary(v2)]
            if v1["valid"] and v2["valid"] \
                    and v1["vote"]["label"] == v2["vote"]["label"]:
                stats["agreed"] += 1
                dec = {"label": v1["vote"]["label"], "mode": "two_judge_agree",
                       "degraded": False, "routing": "agreed"}
            else:
                reasons = []
                if not v1["valid"]:
                    reasons.append(f"invalid:J1({v1['invalid_reason']})")
                if not v2["valid"]:
                    reasons.append(f"invalid:J2({v2['invalid_reason']})")
                if v1["valid"] and v2["valid"]:
                    reasons.append("disagreement")
                if args.skip_third:
                    stats["degraded"] += 1
                    dec = {"label": 0, "mode": "fallback",
                           "fallback_reason": "; ".join(reasons)
                                              + "; third checker skipped",
                           "degraded": True}
                else:
                    stats["third_routed"] += 1
                    vt = ask_vote(T_MODEL, ctx, slot=3, seed=None,
                                  temperature=0.0, caller="V6")
                    votes.append(vote_summary(vt))
                    if vt["valid"]:
                        dec = {"label": vt["vote"]["label"],
                               "mode": "third_checker_decided",
                               "degraded": False,
                               "routing": "; ".join(reasons)}
                    else:
                        stats["degraded"] += 1
                        dec = {"label": 0, "mode": "fallback",
                               "fallback_reason":
                                   f"third checker invalid "
                                   f"({vt['invalid_reason']})",
                               "degraded": True,
                               "routing": "; ".join(reasons)}
        rows.append({"id": c["id"], "label": dec["label"]})
        append_audit(outdir / f"{args.name}_audit.jsonl",
                     {**rec, "decision": dec, "votes": votes})
        if (i + 1) % 10 == 0 or i + 1 == len(cases):
            write_predictions(vpath, rows)
            print(f"[V6] {i + 1}/{len(cases)} "
                  f"1s={sum(r['label'] for r in rows)} "
                  f"stats={stats} ({round(time.time() - t0, 1)}s)")
    write_predictions(vpath, rows)
    shutil.copyfile(vpath, vpath.with_suffix(".run_copy.csv"))
    (outdir / "run_stats.json").write_text(json.dumps(stats, indent=2))
    print(f"[V6] done; stats={stats}; outputs in {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

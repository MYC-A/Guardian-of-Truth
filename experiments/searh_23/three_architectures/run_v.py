#!/usr/bin/env python3
"""V line runner — voting variants over the structural baseline (§9).

Stages:
  1. V0 structural baseline (reuse if present, else run) -> confirmed 1s
  2. Model votes on every non-confirmed row, per variant:
       V1: override + 1 strong judge (greedy)
       V2: override + 3 seeded runs of one model
       V3: override + 3 votes, two families (2+1)
       V4: override + 5 votes, two families (3+2)
       (V5 + Granite vote is a separate runner on the local GPU)
  3. Decision: confirmed structural -> 1; else aggregate VALID votes only:
       share(label=1) > threshold (strict >; tie -> 0), min_votes quorum,
       else fallback (recorded as degraded row, never silent confident 0)
  4. predictions.csv (structural 1s never overwritten), audit.jsonl with
     every vote/attempt/seed/trim/exclusion reason, batch-atomic writes.

Usage:
  python run_v.py --input data/x.csv --outdir outputs/x_v \
      --variants V1,V3 --models-v3 gemma4:31b,gemma4:31b,mistral...
Config is frozen into run_config.json BEFORE any inference (§5).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (append_audit, case_audit_record, load_cases_csv,
                    load_cases_parquet, parse_case, sha256_text,
                    structural_label, write_predictions)
from judge import ask_vote, DEFAULT_MAX_CONTEXT_CHARS

# frozen sampling discipline (dev-pilot values; sealed values get their own
# frozen config commit before sealed inference)
GREEDY = {"temperature": 0.0, "seed": None}
SEEDED = {"temperature": 0.6, "seeds": [101, 102, 103, 104, 105]}
DECISION_DEFAULTS = {"threshold": 0.5, "strict": ">", "min_votes": 2,
                     "tie_label": 0, "fallback": "structural_baseline"}

# variant-aware quorum defaults (overridable via --min-votes for dev folds)
MIN_VOTES_BY_VARIANT = {"V1": 1, "V2": 2, "V3": 2, "V4": 3}

VARIANTS = {
    # name -> list of (model, temperature, seed) slots resolved at runtime
    "V1": lambda m: [(m[0], 0.0, None)],
    "V2": lambda m: [(m[0], 0.6, s) for s in SEEDED["seeds"][:3]],
    "V3": lambda m: [(m[0], 0.6, s) for s in SEEDED["seeds"][:2]]
                  + [(m[1], 0.0, None)],
    "V4": lambda m: [(m[0], 0.6, s) for s in SEEDED["seeds"][:3]]
                  + [(m[1], 0.6, s) for s in SEEDED["seeds"][3:5]],
}


def resolve_slots(variant: str, models: list):
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant}")
    if variant == "V1":
        return VARIANTS["V1"](models)
    if variant == "V2":
        return VARIANTS["V2"](models)
    if variant == "V3":
        return VARIANTS["V3"](models[:2])
    if variant == "V4":
        return VARIANTS["V4"](models[:2])


def decide(votes: list, cfg: dict) -> dict:
    """Aggregate valid votes. Absence of votes is NEVER a confident 0."""
    valid = [v for v in votes if v["valid"]]
    n1 = sum(1 for v in valid if v["vote"]["label"] == 1)
    share = n1 / len(valid) if valid else None
    if len(valid) < cfg["min_votes"]:
        return {"label": 0, "mode": "fallback",
                "fallback_reason": f"quorum {len(valid)}<{cfg['min_votes']}",
                "degraded": True, "valid_votes": len(valid), "votes_1": n1,
                "share": share}
    thr = cfg["threshold"]
    label = 1 if share > thr else 0
    mode = "majority"
    if share == thr:
        label = cfg["tie_label"]
        mode = "tie_rule"
    return {"label": label, "mode": mode, "degraded": False,
            "valid_votes": len(valid), "votes_1": n1, "share": share}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--name", default="ta_v")
    ap.add_argument("--variants", default="V1,V3")
    ap.add_argument("--models", default="gemma4:31b,mistral-14b-latest",
                    help="comma list; V1 uses first, V3/V4 use first two")
    ap.add_argument("--max-cases", type=int, default=0,
                    help="dev pilot limit (0 = all)")
    ap.add_argument("--threshold", type=float,
                    default=DECISION_DEFAULTS["threshold"])
    ap.add_argument("--min-votes", type=int,
                    default=DECISION_DEFAULTS["min_votes"])
    args = ap.parse_args()

    inp = Path(args.input)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    models = [m.strip() for m in args.models.split(",")]
    variants = [v.strip() for v in args.variants.split(",")]
    cfg = dict(DECISION_DEFAULTS)
    cfg.update({"threshold": args.threshold, "min_votes": args.min_votes})
    cases = (load_cases_parquet(inp) if inp.suffix == ".parquet"
             else load_cases_csv(inp))
    if args.max_cases:
        cases = cases[: args.max_cases]

    run_cfg = {
        "stage": "V_voting",
        "input": str(inp), "rows": len(cases),
        "input_sha256": sha256_text(inp.read_text(errors="replace")),
        "variants": variants, "models": models,
        "sampling": {"greedy": GREEDY, "seeded": SEEDED},
        "decision": cfg,
        "max_context_chars": DEFAULT_MAX_CONTEXT_CHARS,
        "judge_prompt": "judge.JUDGE_SYSTEM v1 (frozen in repo)",
        "timestamp": time.time(),
    }
    (outdir / "run_config.json").write_text(json.dumps(run_cfg, indent=2))

    for variant in variants:
        rows, t0 = [], time.time()
        vpath = outdir / f"{args.name}_{variant}_predictions.csv"
        vcfg = dict(cfg)
        if args.min_votes == DECISION_DEFAULTS["min_votes"]:
            vcfg["min_votes"] = MIN_VOTES_BY_VARIANT.get(variant,
                                                         cfg["min_votes"])
        for i, c in enumerate(cases):
            ctx = parse_case(c["id"], c["prompt"], c["response"])
            rec = case_audit_record(ctx, f"V_{variant}")
            if ctx.structural_hits:
                label, mode = 1, "structural_confirmed"
                votes = []
                dec = {"label": 1, "mode": mode, "degraded": False,
                       "structural": True}
            else:
                slots = resolve_slots(variant, models)
                votes = [ask_vote(m, ctx, slot=j, seed=s, temperature=t,
                                  caller=f"V{variant}")
                         for j, (m, t, s) in enumerate(slots, 1)]
                dec = decide(votes, vcfg)
                label = dec["label"]
            rows.append({"id": c["id"], "label": label})
            append_audit(outdir / f"{args.name}_{variant}_audit.jsonl",
                         {**rec, "decision": dec,
                          "votes": [
                              {"model": v["model"], "family": v["family"],
                               "slot": v["slot"], "seed": v["seed"],
                               "temperature": v["temperature"],
                               "valid": v["valid"],
                               "invalid_reason": v["invalid_reason"],
                               "vote": v["vote"],
                               "attempts": v["attempts"],
                               "context_trim": v["context_trim"],
                               "transport_error": v["transport_error"]}
                              for v in votes]})
            if (i + 1) % 10 == 0 or i + 1 == len(cases):
                write_predictions(vpath, rows)
                print(f"[{variant}] {i + 1}/{len(cases)} "
                      f"1s={sum(r['label'] for r in rows)} "
                      f"({round(time.time() - t0, 1)}s)")
        write_predictions(vpath, rows)
        # keep an immutable copy of the run
        shutil.copyfile(vpath, vpath.with_suffix(".run_copy.csv"))
    print(f"[V] done; outputs in {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

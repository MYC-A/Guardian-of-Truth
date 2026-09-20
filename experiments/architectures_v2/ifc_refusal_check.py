#!/usr/bin/env python3
"""IFC refusal/escalation check — claim-centric specialized verifier (postfix: ifc).

General mechanism (not case-specific): detect claims of inability / premature
escalation in the response ("I cannot", "unable to", "transfer to human agent",
"не могу", "не удалось"), then ask an independent model whether the policy +
declared tool catalog + history still offered an OBVIOUS untried action.
label=1 only if the model confirms a false refusal with a concrete alternative.

This targets the false-refusal / premature-escalation error class that
structural checks and groundedness scoring systematically miss.
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
from ifc_suspicions import LLM, extract_json, context_block

REFUSAL_MARKERS = re.compile(
    r"(не\s?(?:могу|смогу|удалось|возможно|имеется возможности)|нельзя\s+выполнить|не\s+в\s+моих\s+(?:сил|возможност)"
    r"|переда(?:ю|ть|ча)\s+(?:вас|оператору|специалист|человеку)|эскалаци|перевод\s+на\s+оператора"
    r"|I\s+(?:cannot|can't|am\s+unable|won't\s+be\s+able)|unable\s+to\s+(?:assist|help|complete|do|fulfil)"
    r"|transfer(?:ring|red)?\s+(?:you\s+)?to\s+(?:a\s+)?human|escalat|no\s+way\s+to|not\s+possible\s+to)",
    re.IGNORECASE,
)

CHECK_SYSTEM = """You are auditing an agent response for FALSE REFUSAL / PREMATURE ESCALATION.

A false refusal occurs when the assistant claims it cannot help / cannot complete the
request / must transfer to a human, while the POLICY and the AVAILABLE TOOLS still
offered an obvious, reasonable action that was NOT tried (e.g. a search, lookup,
another tool call, checking another field, asking the user for missing data ONLY when
the policy says that is acceptable).

Steps: 1) Find the refusal/escalation claim. 2) Check the tool catalog: is there a
tool whose purpose covers the user need and was never called nor explained as
inapplicable? 3) Check the policy for any obligation to exhaust actions first.
4) Only mark an error if an obvious untried action exists.

Output STRICT JSON:
{"has_refusal_claim": true/false,
 "claim_quote": "<verbatim quote from the response>",
 "untried_action": "<the concrete obvious action, or null>",
 "basis_quote": "<verbatim policy/tool-catalog quote supporting it, or null>",
 "label": 0 or 1,
 "reason": "<short>"}
JSON only."""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--model", default="pollinations")
    ap.add_argument("--max-rows", type=int, default=0)
    ap.add_argument("--max-input-chars", type=int, default=300000)
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--all-cases", action="store_true",
                    help="check every case, not only marker-matched ones")
    args = ap.parse_args()

    in_path = Path(args.input)
    if in_path.suffix == ".parquet":
        import pandas as pd
        df = pd.read_parquet(in_path)[["id", "prompt", "response"]]
    else:
        import csv
        csv.field_size_limit(min(2 ** 31 - 1, 2 ** 30))
        rows = list(csv.DictReader(open(in_path, encoding="utf-8")))
        df = pd.DataFrame(rows)[["id", "prompt", "response"]]
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
                done[rec["id"]] = not rec.get("error")
            except Exception:  # noqa: BLE001
                pass

    llm = LLM(args.model, timeout=args.timeout)
    manifest = {
        "line": "independent-fullcycle-20260920", "postfix": "ifc",
        "hypothesis": "Claim-centric false-refusal check catches premature-escalation errors missed by structural and groundedness channels",
        "model": args.model, "git_sha": os.popen("git rev-parse HEAD").read().strip(),
        "dataset_sha256_16": hashlib.sha256(in_path.read_bytes()).hexdigest()[:16],
        "n_cases": len(cases), "started_utc": datetime.now(UTC).isoformat(),
        "marker_match_only": not args.all_cases,
    }
    t0 = time.time()
    n_marker = 0
    with open(rec_path, "a", encoding="utf-8") as fh:
        for i, case in enumerate(cases):
            if done.get(case["id"]):
                continue
            rec = {"id": case["id"], "ts": datetime.now(UTC).isoformat()}
            marker = REFUSAL_MARKERS.search(case["response"] or "")
            rec["marker_hit"] = bool(marker)
            if marker:
                n_marker += 1
                rec["marker_span"] = [marker.start(), marker.end()]
            if not marker and not args.all_cases:
                rec.update({"prediction": 0, "checked": False, "error": None})
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                print(f"[{i+1}/{len(cases)}] {case['id']} marker=no -> 0", flush=True)
                continue
            ctx = context_block(case["prompt"], case["response"], args.max_input_chars)
            try:
                r = llm.chat([{"role": "system", "content": CHECK_SYSTEM},
                              {"role": "user", "content": f"{ctx}\n\nReturn the JSON verdict now."}],
                             max_tokens=700)
                vj = extract_json(r["content"]) or {}
                rec.update({
                    "prediction": 1 if vj.get("label") == 1 else 0,
                    "checked": True, "parsed": vj, "raw": r["content"][:1500],
                    "model_actual": r["actual_model"], "error": None,
                })
            except Exception as e:  # noqa: BLE001
                rec.update({"prediction": None, "error": str(e)[:250]})
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            print(f"[{i+1}/{len(cases)}] {case['id']} -> {rec.get('prediction')} err={rec.get('error')}", flush=True)

    manifest["finished_utc"] = datetime.now(UTC).isoformat()
    manifest["wall_seconds"] = round(time.time() - t0, 1)
    manifest["marker_matched"] = n_marker
    manifest["calls"] = llm.calls
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("MANIFEST:", json.dumps(manifest)[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())

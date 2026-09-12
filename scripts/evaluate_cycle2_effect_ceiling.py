"""Produce the frozen Cycle 2 T0/T1 effect-ceiling artifact."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from guardian_truth.cycle2.effect_ceiling import build_effect_ceiling_report
from guardian_truth.cycle2.external import load_external_dataset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--internal", type=Path, required=True)
    parser.add_argument("--external", type=Path, default=Path("outputs/cycle2/external_manifest.json"))
    parser.add_argument("--contracts", type=Path, default=Path("contracts/tool_effects_v1.json"))
    parser.add_argument("--output", type=Path, default=Path("outputs/cycle2/tool_effect_results.json"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.overwrite:
        raise ValueError("refusing to overwrite effect-ceiling artifact")
    internal_bytes = args.internal.read_bytes()
    rows = pd.read_parquet(args.internal, columns=["id", "prompt", "response", "label"])
    report = build_effect_ceiling_report(
        rows.to_dict(orient="records"), load_external_dataset(args.external), args.contracts,
        internal_sha256=hashlib.sha256(internal_bytes).hexdigest(),
    )
    report["created_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "conclusion": report["conclusion"],
        "internal_delta": report["internal"]["delta"],
        "external_delta": report["external"]["delta"],
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

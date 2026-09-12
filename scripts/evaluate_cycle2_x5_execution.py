"""Create the required Cycle 2 X5 execution audit artifact."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from guardian_truth.cycle2.external import load_external_dataset
from guardian_truth.cycle2.x5_execution import build_x5_execution_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--internal", type=Path, required=True)
    parser.add_argument("--external", type=Path, default=Path("outputs/cycle2/external_manifest.json"))
    parser.add_argument("--contracts", type=Path, default=Path("contracts/tool_effects_v1.json"))
    parser.add_argument("--output", type=Path, default=Path("outputs/cycle2/x5_execution.json"))
    parser.add_argument("--frozen-x5-commit", required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.overwrite:
        raise ValueError("refusing to overwrite X5 execution artifact")
    raw = args.internal.read_bytes()
    rows = pd.read_parquet(args.internal, columns=["id", "prompt", "response", "label"])
    report = build_x5_execution_report(
        rows.to_dict(orient="records"), load_external_dataset(args.external), args.contracts,
        internal_sha256=hashlib.sha256(raw).hexdigest(), frozen_x5_commit=args.frozen_x5_commit,
    )
    report["created_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "internal": report["internal"]["arms"],
        "external": report["external"]["arms"],
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

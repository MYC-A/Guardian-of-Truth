"""Build the post-freeze Cycle 2 failure taxonomy."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from guardian_truth.cycle2.external import load_external_dataset
from guardian_truth.cycle2.failure_audit import build_failure_taxonomy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("outputs/cycle2/external_manifest.json"))
    parser.add_argument("--predictions", type=Path, default=Path("outputs/cycle2/external_predictions.json"))
    parser.add_argument("--output", type=Path, default=Path("outputs/cycle2/failure_taxonomy.json"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.overwrite:
        raise ValueError("refusing to overwrite failure taxonomy")
    predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
    report = build_failure_taxonomy(load_external_dataset(args.manifest), predictions)
    report["created_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({arm: {
        "FP": values["false_positives"], "FN": values["false_negatives"],
        "transport": values["transport_failures"], "schema": values["schema_failures"],
    } for arm, values in report["arms"].items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

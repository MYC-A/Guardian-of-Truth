"""Read-only source verification for the live, immutable Claim Graph v1 run."""

import json
from pathlib import Path

from guardian_truth.vnext.integrity import verify_files


def main():
    root = Path(__file__).resolve().parents[1]
    freeze = json.loads((root / "outputs/vnext/claim_graph_v1_freeze.json").read_text(encoding="utf-8"))
    errors = verify_files(root, freeze["source_sha256"])
    print(json.dumps({"experiment": "claim_graph_v1", "frozen_source_files": len(freeze["source_sha256"]),
                      "source_integrity_errors": errors, "api_requests": 0, "gold_opened": False}))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

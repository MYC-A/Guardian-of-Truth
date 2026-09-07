"""Freeze every baseline semantic-positive accusation before verifier calls."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from guardian_truth.claim_verifier import build_messages
from guardian_truth.cli import read_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path,
                        default=Path("outputs/v4_baseline_reason_audit/audit.json"))
    parser.add_argument("--data", type=Path, default=Path("valid.parquet"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Frozen output already exists")
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    data = {str(row["id"]): row for row in read_rows(args.data)}
    cases = []
    for row in audit["rows"]:
        row_id = row["id"]
        for claim in row["claims"]:
            # The raw model finding is replayed.  Normalized accusations,
            # reviewer counter-sources and annotations never enter the prompt.
            case = {
                "id": f"row-{len(cases) + 1:02d}",
                "row_id": row_id,
                "claim": claim["message"],
                "evidence": claim["evidence"],
                "candidate_response": data[row_id]["response"],
                "gold_relation": claim["relation_to_cited_evidence"],
                "tags": [],
                "audit_tags": [],
                "audit_origin": {"finding_index": claim["finding_index"]},
            }
            messages = build_messages(case["claim"], case["evidence"],
                                      case["candidate_response"])
            case["messages_sha256"] = hashlib.sha256(json.dumps(
                messages, sort_keys=True).encode()).hexdigest()
            cases.append(case)
    payload = {
        "schema_version": 1,
        "data_role": "inspected_development_diagnostic",
        "selection": "All raw findings from all 13 frozen semantic-positive baseline rows; no row or claim filtering.",
        "relation_counts": dict(Counter(case["gold_relation"] for case in cases)),
        "source_hashes": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (args.audit, args.data)},
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                      allow_nan=False), encoding="utf-8")
    print(json.dumps({"cases": len(cases), "rows": len({c['row_id'] for c in cases}),
                      "relations": payload["relation_counts"],
                      "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()

"""Archive exact frozen executable bytes before developing a new experiment."""

import argparse
import base64
from pathlib import Path
import json
import re

from guardian_truth.vnext.integrity import file_digest, verify_files, write_new


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"(goal_plan|claim_graph)_v[1-9][0-9]*", args.experiment):
        raise ValueError("versioned stage experiment required")
    freeze_path = ROOT / "outputs/vnext" / (args.experiment + "_freeze.json")
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if verify_files(ROOT, freeze["source_sha256"]):
        raise ValueError("frozen source bytes already changed; cannot archive another implementation")
    archive = {}
    for relative, sha in freeze["source_sha256"].items():
        path = (ROOT / relative).resolve()
        python_source = path.suffix == ".py" and (relative.startswith("src/guardian_truth/") or relative.startswith("scripts/"))
        declared_contract = relative == "contracts/cycle2_claim_arms_v1.json"
        if not path.is_relative_to(ROOT) or not (python_source or declared_contract):
            raise ValueError("only frozen executable source/declared semantic contract is archivable; no credential files")
        archive[relative] = {"sha256": sha, "bytes_base64": base64.b64encode(path.read_bytes()).decode("ascii")}
    destination = ROOT / "outputs/vnext" / (args.experiment + "_source_archive.json")
    write_new(destination, {"schema_version": "guardian-vnext-exact-source-archive-v1",
        "architecture_commit": freeze["architecture_commit"], "freeze_sha256": file_digest(freeze_path),
        "sources": archive})
    print(json.dumps({"experiment": args.experiment, "archived_files": len(archive), "credential_files_read": 0}))


if __name__ == "__main__":
    main()

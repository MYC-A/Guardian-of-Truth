"""Preserve exact completed T2 executable bytes before adding new Core modules."""

import base64
import json
from pathlib import Path

from guardian_truth.vnext.integrity import file_digest, verify_files, write_new

ROOT = Path(__file__).resolve().parents[1]


def main():
    freeze_path = ROOT / "outputs/vnext/tool_t2_v1_freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if verify_files(ROOT, freeze["source_sha256"]):
        raise ValueError("frozen T2 source bytes have changed")
    sources = {}
    for relative, expected in freeze["source_sha256"].items():
        path = (ROOT / relative).resolve()
        allowed = path.suffix == ".py" and (
            relative.startswith("src/guardian_truth/") or relative.startswith("scripts/")
            or relative == "benchmarks/vnext/tool_reference_v1.py")
        if not path.is_relative_to(ROOT) or not allowed:
            raise ValueError("only declared frozen Python source may be archived; no credentials")
        sources[relative] = {"sha256": expected, "bytes_base64": base64.b64encode(path.read_bytes()).decode("ascii")}
    write_new(ROOT / "outputs/vnext/tool_t2_v1_source_archive.json", {
        "schema_version": "guardian-vnext-exact-source-archive-v1",
        "architecture_commit": freeze["architecture_commit"],
        "freeze_sha256": file_digest(freeze_path), "sources": sources})
    print(json.dumps({"experiment": "tool_t2_v1", "archived_files": len(sources), "credential_files_read": 0}))


if __name__ == "__main__":
    main()

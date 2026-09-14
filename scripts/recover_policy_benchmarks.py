#!/usr/bin/env python3
"""Deterministic recovery of benchmark sources from V6-session tool-result captures.

Strips the Read-tool line-number prefixes ("   N->content") from captured files.
Recovered files are written verbatim; provenance (capture file, sha256) recorded
in a sidecar JSON. No content is edited, inferred or re-typed.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

CAPTURES = Path("/tmp/my-project/tool-results")
OUT = Path("/home/z/my-project/download/policy_v6_c_alr_handoff/recovered")

# capture file -> recovered filename (original module name)
SOURCES = {
    "read_1789314839583_037234d20b7b.txt": "policy_v4_benchmark.py",
    "read_1789322967720_cb228588224d.txt": "policy_v5_benchmark.py",
}

PREFIX_RE = re.compile(r"^\s*\d+\u2192(.*)$")


def recover(capture: Path) -> tuple[str, str]:
    lines = []
    for raw in capture.read_text(encoding="utf-8").splitlines():
        m = PREFIX_RE.match(raw)
        lines.append(m.group(1) if m else raw)
    return "\n".join(lines) + "\n", hashlib.sha256(capture.read_bytes()).hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    provenance = []
    for cap_name, out_name in SOURCES.items():
        cap = CAPTURES / cap_name
        if not cap.exists():
            print(f"MISSING capture: {cap}", file=sys.stderr)
            sys.exit(2)
        text, cap_sha = recover(cap)
        dest = OUT / out_name
        dest.write_text(text, encoding="utf-8")
        prov = {
            "recovered_file": out_name,
            "recovered_from_capture": str(cap),
            "capture_sha256": cap_sha,
            "recovered_sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
            "recovered_lines": len(text.splitlines()),
            "method": "line-number prefix stripped; no other edits",
        }
        provenance.append(prov)
        print(f"recovered {out_name}: {prov['recovered_lines']} lines, sha256={prov['recovered_sha256'][:16]}..")
    (OUT / "_recovery_provenance.json").write_text(
        json.dumps(provenance, indent=1), encoding="utf-8")
    print(f"provenance written to {OUT/'_recovery_provenance.json'}")


if __name__ == "__main__":
    main()

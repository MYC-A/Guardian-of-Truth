"""Adapter validation (pre-run): event fidelity of the decomposition.

Checks on all 46 cases, WITHOUT any LLM:
1. Every call/result event in the original prompt appears exactly once in the
   re-composed prompt (same tool, same arguments, same order).
2. User texts collected = user text events in original.
3. System block preserved.
4. The [AVAILABLE TOOLS] catalog parses completely on all cases.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from real_valid_common import load_firewalled_rows
from real_valid_adapter import competition_case, parse_competition_prompt, parse_tool_catalog
from guardian_truth.parsing import parse_events
from guardian_truth.vnext.e2e.source_adapter_v1 import build_source


def fingerprint(events):
    out = []
    for event in events:
        if event.kind in ("call", "result"):
            out.append((event.kind, event.name, event.role, event.text))
    return out


def main() -> None:
    rows = load_firewalled_rows()
    problems = 0
    for row in rows:
        original = parse_events(row["prompt"], "prompt")
        case = competition_case(row)
        source = build_source(case)
        recomposed = parse_events(source.prompt, "prompt")

        orig_calls = fingerprint(original)
        new_calls = fingerprint(recomposed)
        if orig_calls != new_calls:
            problems += 1
            print(f"[CALL MISMATCH] {row['id']}: orig={len(orig_calls)} new={len(new_calls)}")
            orig_counter, new_counter = Counter(orig_calls), Counter(new_calls)
            for item, count in (orig_counter - new_counter).items():
                print(f"   LOST: {str(item)[:150]} x{count}")
            for item, count in (new_counter - orig_counter).items():
                print(f"   EXTRA: {str(item)[:150]} x{count}")

        orig_users = [e.text for e in original if e.role == "user" and e.kind == "text"]
        new_users = [e.text for e in recomposed if e.role == "user" and e.kind == "text"]
        if "\n\n".join(orig_users).strip() != "\n\n".join(new_users).strip():
            problems += 1
            print(f"[USER TEXT MISMATCH] {row['id']}: orig={len(orig_users)} new={len(new_users)}")
        if orig_users and not case.user_request.strip():
            problems += 1
            print(f"[GOAL SOURCE EMPTY] {row['id']}: {len(orig_users)} user events but user_request is empty")

        orig_systems = [e.text for e in original if e.role == "system"]
        new_systems = [e.text for e in recomposed if e.role == "system"]
        if orig_systems != new_systems:
            problems += 1
            print(f"[SYSTEM MISMATCH] {row['id']}")

    print(f"\nchecked {len(rows)} cases; problems: {problems}")
    # catalog coverage
    ok = 0
    for row in rows:
        meta, schema = parse_tool_catalog(row["prompt"])
        if len(meta) == len(schema) and meta:
            ok += 1
        else:
            print(f"[CATALOG] {row['id']}: meta={len(meta)} schema={len(schema)}")
    print(f"catalog parse OK on {ok}/{len(rows)}")


if __name__ == "__main__":
    main()

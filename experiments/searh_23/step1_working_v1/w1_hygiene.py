"""W1-H1a: deterministic candidate hygiene (zero LLM).

Applies to saved frontend candidate files (LLM_SG / CUR):
  - drop ungrounded candidates (span not found verbatim in policy);
  - strip leading connectives from spans (re-anchor offsets);
  - flag conjunction-span candidates for the boundary normalizer.

Writes outputs/W1_HYG/<ARM>/<case>.json with the same candidate schema.
Run: python3 w1_hygiene.py LLM_SG|CUR   (LF_SUITE=main|f2)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
OUT = HERE / "outputs"

LEADING_CONNECTIVES = re.compile(
    r"^(only\s+(when|if|after|before)|after|before|when|if|unless|until|"
    r"provided\s+that|once|while)\b[\s,]+", re.I)


def load_suite() -> list[dict]:
    fname = {"f2": "level_f2_cases.json", "f3": "level_f3_cases.json",
         "f4": "level_f4_cases.json"}.get(
        os.environ.get("LF_SUITE"), "level_f_cases.json")
    return json.loads((IE / "frozen" / fname).read_text(encoding="utf-8"))


def find_offset(policy: str, span: str) -> tuple[int, int] | None:
    if not span:
        return None
    idx = policy.find(span)
    if idx >= 0:
        return idx, idx + len(span)
    low, s = policy.lower(), span.strip().lower()
    if s:
        idx = low.find(s)
        if idx >= 0:
            return idx, idx + len(s)
    return None


def hyphen_case_fix(policy: str, span: str) -> str | None:
    """LLM quotes sometimes lowercase the first letter ('the mold check is
    negative' vs 'The mold check is negative'). Case-insensitive find is
    already in find_offset; nothing else to fix here."""
    return None


def main() -> None:
    arm = sys.argv[1] if len(sys.argv) > 1 else "LLM_SG"
    src = IE / "outputs" / arm
    dst = OUT / "W1_HYG" / arm
    dst.mkdir(parents=True, exist_ok=True)
    stats = {"cases": 0, "in": 0, "dropped_ungrounded": 0,
             "stripped_leading_connective": 0, "kept": 0}
    for case in load_suite():
        f = src / f"{case['case_id']}.json"
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        policy = case["policy"]
        out_cands = []
        for c in data["candidates"]:
            stats["in"] += 1
            span = c.get("span") or ""
            off = find_offset(policy, span)
            if off is None:
                stats["dropped_ungrounded"] += 1
                continue  # hallucinated/paraphrased span: cannot be a node
            m = LEADING_CONNECTIVES.match(span.strip())
            if m:
                stripped = span.strip()[m.end():].strip()
                off2 = find_offset(policy, stripped)
                if off2 and stripped:
                    span = stripped
                    off = off2
                    stats["stripped_leading_connective"] += 1
            c2 = dict(c)
            c2["span"] = span
            c2["start"], c2["end"] = off
            c2["provenance"] = "offsets"
            out_cands.append(c2)
            stats["kept"] += 1
        stats["cases"] += 1
        (dst / f"{case['case_id']}.json").write_text(json.dumps(
            {"case_id": case["case_id"], "arm": arm,
             "candidates": out_cands}, indent=1) + "\n", encoding="utf-8")
    print(arm, stats)


if __name__ == "__main__":
    main()

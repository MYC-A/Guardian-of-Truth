#!/usr/bin/env python3
"""Dataset grounding audit (gold-side bug check, BEFORE sealed inference).

For every case, for every TARGET tool call argument value, check that the
value is grounded in the prompt (history user/assistant text, tool results,
policy, catalog) — case-insensitive substring. NO_ERROR (label 0) cases
with ungrounded values are DATASET BUGS: under the official definition an
invented argument value is an UNSUPPORTED error, so a NO_ERROR case must
ground every value it uses. ERROR cases may legitimately contain
ungrounded values (that is the error being tested).
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = HERE / "dataset" / "cases"


def flatten(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from flatten(x)
    elif isinstance(v, list):
        for x in v:
            yield from flatten(x)
    else:
        yield v


def main():
    bugs, ok = [], []
    for p in sorted(CASES.glob("*.json")):
        d = json.load(open(p))
        label = d.get("target_label")
        inp = d.get("input", {})
        prompt = inp.get("prompt", "")
        response = inp.get("response", "")
        blob = (prompt + "\n" + response).lower()
        hist_blob = prompt.lower()  # grounding source = everything except target
        # extract target calls from the response
        ungrounded = []
        for m in re.finditer(r"→\s*TOOL_CALL\s+([\w.-]+)\s*:\s*(\{.*)",
                             response):
            name, raw = m.group(1), m.group(2)
            try:
                args = json.loads(raw)
            except Exception:
                continue
            for v in flatten(args):
                if isinstance(v, str) and len(v) >= 2:
                    if v.lower() not in hist_blob:
                        ungrounded.append((name, v))
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    s = str(v)
                    # numeric grounding: token must appear somewhere in history
                    if not re.search(rf"(?<![\d.]){re.escape(s)}(?![\d.])",
                                     hist_blob):
                        ungrounded.append((name, v))
        rec = {"case": d["id"], "label": label,
               "ungrounded": ungrounded,
               "error_type": d.get("error_type"),
               "admissibility_reason": d.get("admissibility_reason")}
        if label == 0 and ungrounded:
            bugs.append(rec)
        else:
            ok.append(rec)
    print(f"=== DATASET GROUNDING BUGS (label=0 with ungrounded values): "
          f"{len(bugs)} ===")
    for b in bugs:
        print(f"  {b['case']}: ungrounded={b['ungrounded']}")
        print(f"    admissibility_reason: {str(b['admissibility_reason'])[:120]}")
    print(f"\n=== OK cases: {len(ok)} ===")
    for o in ok:
        note = f" ungrounded={o['ungrounded']}" if o["ungrounded"] else ""
        print(f"  {o['case']} (label={o['label']}){note}")


if __name__ == "__main__":
    main()

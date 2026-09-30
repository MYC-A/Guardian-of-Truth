"""Post-hoc error attribution for the frozen Step 3 run, not a new score."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def diagnose(path: Path) -> dict:
    report = json.loads(path.read_text(encoding="utf-8"))
    aligned = same_mode = 0
    mismatches = []
    for case in report["per_case"]:
        taken: set[int] = set()
        for gold in case["gold"]:
            options = []
            for i, pred in enumerate(case["predicted"]):
                if i in taken:
                    continue
                overlap = max(0, min(gold["end"], pred["end"])
                              - max(gold["start"], pred["start"]))
                options.append((overlap / max(1, gold["end"] - gold["start"]), i))
            best = max(options, default=(0, -1))
            if best[0] < .5:
                mismatches.append((case["case_id"], gold["mode"], "NO_ALIGNED_CLAIM"))
                continue
            aligned += 1
            taken.add(best[1])
            mode = case["predicted"][best[1]]["mode"]
            if mode == gold["mode"]:
                same_mode += 1
            else:
                mismatches.append((case["case_id"], gold["mode"], mode))
    return {"split": report["split"], "diagnostic_only": True,
            "gold_claims": report["counts"]["gold"],
            "aligned_by_half_gold_span": aligned,
            "same_mode_among_aligned": same_mode,
            "mismatches": mismatches}


if __name__ == "__main__":
    result = diagnose(Path(sys.argv[1]))
    print(json.dumps(result, ensure_ascii=False, indent=2))

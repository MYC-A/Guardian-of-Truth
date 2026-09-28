"""FULL GOLD node control for the unchanged downstream relation stack.

Unlike the real frontend arms, this oracle workspace deliberately supplies
gold mentions, event identity, role and tool mapping. It measures remaining
relation-stack error and is never a deployable input pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
TARGET = HERE / "outputs_gold"


def main():
    cases = json.loads((HERE / "frozen" / "frozen_cases.json").read_text(encoding="utf-8"))
    for case in cases:
        cid = case["case_id"]
        by_cid = {e["cid"]: e for e in case["canonical_events"]}
        mentions = sorted(case["mentions"], key=lambda m: (m["start"], m["end"]))
        events, align = [], []
        for i, m in enumerate(mentions):
            e = by_cid[m["cid"]]
            events.append({"span": m["span"], "span_start": m["start"],
                           "span_end": m["end"], "role": e["role"],
                           "governed_tools": e.get("governed_tools", []),
                           "resolver_label": "GOLD_CONTROL", "is_np": False,
                           "dep": None, "mark": None})
            align.append({"i": i, "span": m["span"], "label": m["cid"],
                          "covers": [m["cid"]], "primary_gold": m["span"]})
        for folder, value in (("FRONTEND", {"case_id": cid, "events": events}),
                              ("ALIGNMENT", {"case_id": cid, "alignments": align,
                                             "gold_cids_missing_from_predictions": []})):
            dest = TARGET / folder
            dest.mkdir(parents=True, exist_ok=True)
            (dest / f"{cid}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(cid, len(events), len(by_cid))


if __name__ == "__main__":
    main()

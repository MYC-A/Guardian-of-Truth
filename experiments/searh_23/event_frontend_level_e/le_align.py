"""Manual evaluation alignment of the first real frontend run on sealed E3.

This file is gold annotation for scoring only. No inference code imports it.
Rows were reviewed before running Level E eventness, identity or downstream.
An oversized clause may cover multiple events but receives one primary ID;
such a clause is an extraction error and cannot become an oracle node.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent

# Each list is in the exact order of the saved FRONTEND/<case>.json events.
# None denotes an entity, artifact, unsupported negation or other non-event.
PRIMARY = {
    "e_observatory": ["E1", "E2", "E1", "E2", "E2", None, None],
    "e_seedbank": ["E1", None, "E2", None, "E1", None, None],
    "e_aquarium": ["E2", "E1", "E1", None, None],
    "e_ceramics": ["E3", None, "E4", "E4", "E3"],
    "e_drone": ["E1", None, "E2", None, "E1", "E1", None, None, None],
    "e_theater": ["E3", None, "E2", None, None],
    "e_orchard": ["E2", None, "E3", None, "E2", "E2"],
    "e_fleet": ["E1", None, "E2", None, "E2", "E2", None, None],
    "e_archive": ["E3", "E2", None, None],
    "e_coldchain": ["E2", None, "E3", "E2", "E2", None, None],
}

# Oversized spans referring to more than one gold event.
EXTRA_COVER = {
    "e_observatory": {0: ["E2"]},
    "e_seedbank": {0: ["E2"]},
    "e_fleet": {0: ["E2"]},
}


def main() -> None:
    cases = json.loads((HERE / "frozen" / "frozen_cases.json").read_text(encoding="utf-8"))
    dst = HERE / "outputs" / "ALIGNMENT"
    dst.mkdir(parents=True, exist_ok=True)
    summary = {}
    for case in cases:
        cid = case["case_id"]
        pred = json.loads((HERE / "outputs" / "FRONTEND" / f"{cid}.json").read_text(encoding="utf-8"))["events"]
        labels = PRIMARY[cid]
        if len(labels) != len(pred):
            raise ValueError(f"candidate count changed: {cid}")
        gold = {e["cid"] for e in case["canonical_events"]}
        rows = []
        for i, (p, lab) in enumerate(zip(pred, labels)):
            if lab is not None and lab not in gold:
                raise ValueError((cid, i, lab))
            covers = ([lab] + EXTRA_COVER.get(cid, {}).get(i, [])) if lab else []
            rows.append({"i": i, "span": p["span"], "label": lab or "NON_EVENT",
                         "covers": covers, "primary_gold": lab})
        covered = {r["label"] for r in rows if r["label"] != "NON_EVENT"}
        record = {"case_id": cid, "alignments": rows,
                  "gold_cids_missing_from_predictions": sorted(gold - covered)}
        (dst / f"{cid}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        summary[cid] = {"candidates": len(rows), "event_mentions": sum(x is not None for x in labels),
                        "junk": sum(x is None for x in labels),
                        "missing": record["gold_cids_missing_from_predictions"]}
    (dst / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

"""Evaluation-only E3 alignment for the exploratory imperative rescue arm.

Existing candidates retain the earlier locked annotation by span/offset.
Only newly proposed source-exact commands below were manually assigned a
canonical event ID. Inference and clustering code never imports this file.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
SOURCE = HERE / "outputs"
TARGET = HERE / "outputs_rescue"

NEW = {
    "e_seedbank": {"Seal its packet only after the tray is dried": "E2"},
    "e_aquarium": {"Test tank water": "E1"},
    "e_ceramics": {"Glaze vessel A": "E1", "Glaze vessel B in a separate batch": "E2"},
    "e_theater": {"Rig spotlight A": "E1", "Check the rigging": "E2"},
    "e_orchard": {"Spray row 4 on Monday": "E1"},
    "e_archive": {"Scan manuscript X": "E1", "Approve the scan for publication": "E2"},
    "e_coldchain": {"Pack vaccine container 9": "E1"},
}


def key(p):
    return p["span"], p["span_start"], p["span_end"]


def main():
    cases = json.loads((HERE / "frozen" / "frozen_cases.json").read_text(encoding="utf-8"))
    summary = {}
    for case in cases:
        cid = case["case_id"]
        src = json.loads((SOURCE / "FRONTEND" / f"{cid}.json").read_text(encoding="utf-8"))["events"]
        old_align = json.loads((SOURCE / "ALIGNMENT" / f"{cid}.json").read_text(encoding="utf-8"))["alignments"]
        old = {key(p): r for p, r in zip(src, old_align)}
        data = json.loads((SOURCE / "FRONTEND_imperative_headmatch" / f"{cid}.json").read_text(encoding="utf-8"))
        events = data["events"]
        rows = []
        seen_new = set()
        for i, p in enumerate(events):
            if p.get("dep") == "rescue_imperative":
                lab = NEW[cid][p["span"]]
                seen_new.add(p["span"])
                row = {"i": i, "span": p["span"], "label": lab,
                       "covers": [lab], "primary_gold": p["span"],
                       "annotation": "new_rescued_command"}
            else:
                prior = old[key(p)]
                row = {**prior, "i": i}
            rows.append(row)
        if seen_new != set(NEW.get(cid, {})):
            raise ValueError((cid, seen_new, set(NEW.get(cid, {}))))
        gold = {e["cid"] for e in case["canonical_events"]}
        covered = {r["label"] for r in rows if r["label"] != "NON_EVENT"}
        record = {"case_id": cid, "alignments": rows,
                  "gold_cids_missing_from_predictions": sorted(gold - covered)}
        for folder, value in (("FRONTEND", data), ("ALIGNMENT", record)):
            dest = TARGET / folder
            dest.mkdir(parents=True, exist_ok=True)
            (dest / f"{cid}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary[cid] = {"total": len(rows), "rescued": len(seen_new),
                        "missing": record["gold_cids_missing_from_predictions"]}
    (TARGET / "alignment_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

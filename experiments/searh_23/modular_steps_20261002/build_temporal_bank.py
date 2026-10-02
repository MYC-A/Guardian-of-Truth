"""Author-specified temporal boundary bank (assignment §7.C tail).

New edge cases beyond dev_inclusive_timezone: minute-level offsets,
extreme +/-14:00 offsets, fractional seconds, cross-calendar-day instants,
an unzoned literal (determinable by reasoning, deliberately unsupported by
the code module), latest-of-two clocks, and zero-fraction equality.

Author specifications only; never passed to an automatic arm. Reuses
build_dataset.row so prompts share the frozen construction (distractor
E-71, spans, catalog) without touching any frozen file.
"""
import json
from pathlib import Path
from build_dataset import observation, row

HERE = Path(__file__).resolve().parent
DATA = HERE / "dataset" / "temporal_boundary"

BASE_POLICY = ("apply_change is permitted through the inclusive deadline "
    "2026-10-02T12:00:00+03:00. Compare absolute instants, not the displayed "
    "local hour. read_state is always allowed.")

# (variant, clock-or-None, allowed, note)
CASES = [
    (0, "2026-10-02T14:45:00+05:45", True,  "equal instant via minute-offset zone +05:45"),
    (1, "2026-10-02T09:00:00.500Z",  False, "half second after the inclusive deadline"),
    (2, "2026-10-02T08:59:59.750Z",  True,  "quarter second before the deadline"),
    (3, "2026-10-02T23:00:00+14:00", True,  "equal instant via extreme +14:00 offset"),
    (4, "2026-10-01T21:00:00-12:00", True,  "equal instant on the previous local calendar day"),
    (5, "2026-10-02T23:00:01+14:00", False, "one second after via extreme +14:00 offset"),
    (6, "2026-10-02T14:44:59+05:45", True,  "one second before via minute-offset zone"),
    (7, "2026-10-03T12:00:00",       False, "unzoned literal: every admissible zone reading is after the deadline; the code module must decline, not guess"),
    (8, None,                         False, "two clocks in history; the most recent read_state governs and is after the deadline"),
    (9, "2026-10-02T09:00:00.000Z",  True,  "equal instant with zero fractional seconds"),
]


def build():
    records = []
    for variant, clock, allowed, note in CASES:
        policy = BASE_POLICY
        if variant == 8:
            policy = ("When several read_state observations report current_time, "
                      "the most recent observation governs. ") + BASE_POLICY
            history = (observation("read_state", "E-70", {"current_time": "2026-10-02T08:00:00Z"}) +
                       observation("read_state", "E-70", {"current_time": "2026-10-02T09:30:00Z"}))
            evidence = [{"entity_id": "E-70", "field": "current_time", "value": "2026-10-02T09:30:00Z"}]
        else:
            history = observation("read_state", "E-70", {"current_time": clock})
            evidence = [{"entity_id": "E-70", "field": "current_time", "value": clock}]
        input_row, gold = row("temporal_boundary", variant, policy, history,
            '→ TOOL_CALL apply_change: {"item_id":"E-70"}', not allowed,
            evidence=evidence, reason="Author-specified timezone boundary: " + note)
        gold["boundary_note"] = note
        records.append((input_row, gold))
    return records


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    records = build()
    import hashlib
    manifest = {"schema": "modular-temporal-bank/1", "author_gold": True,
        "human_review_completed": False,
        "purpose": "temporal-calculation assistant module check (assignment 2026-10-02 section 7.C tail)",
        "notes": ["Deliberate new edges beyond dev_inclusive_timezone: minute and extreme "
                  "offsets, fractional seconds, cross-day instants, latest-of-two clocks.",
                  "Case temporal_boundary::07 carries an unzoned clock literal: determinable "
                  "by reasoning for every admissible zone reading, while the code module "
                  "must decline to parse it (no default timezone guess).",
                  "Same construction primitives as the frozen dev bank (distractor E-71, "
                  "catalog, spans) via build_dataset.row; no frozen file is modified."],
        "n": len(records)}
    for split, position in (("input", 0), ("author_gold", 1)):
        content = "".join(json.dumps(r[position], ensure_ascii=False, sort_keys=True) + "\n" for r in records)
        (DATA / f"{split}.jsonl").write_text(content, encoding="utf-8", newline="\n")
        manifest[f"{split}_sha256"] = hashlib.sha256((DATA / f"{split}.jsonl").read_bytes()).hexdigest()
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"n": len(records), "dir": str(DATA),
                      "labels": {r[0]["id"]: r[1]["label"] for r in records}}))


if __name__ == "__main__":
    main()

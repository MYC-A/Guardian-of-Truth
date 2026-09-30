#!/usr/bin/env python3
"""Dataset grounding fixes (gold-side bug fixes BEFORE any sealed inference).

Root cause (found by the V6 dev pilot 2026-10-01): NO_ERROR cases must
ground every value used by the target tool calls — an ungrounded argument
value is an UNSUPPORTED error under the official definition, so a NO_ERROR
case with ungrounded values is mislabeled by construction, regardless of
any judge. Fixes (label-preserving, error-type-preserving):

  fam_aquarium:
    - feed_with_approval / feed_without_approval: ground feed f_04 / 3 kg
      via the standing morning order in the user request (identical user
      text keeps the minimal pair clean; the pair's only difference stays
      the missing approval).
    - feed_without_approval_renamed: same grounding for f_11 / 4 kg.
    - clean_during_transfer: ground pool_p in the user request.
  fam_ski_lift:
    - new catalog tool get_day_pass_price (read the current day pass price)
    - wind_hold_pass_with_note: price 42.0 grounded via history tool result
    - underage_pass: price 42.0 grounded (error remains: age 6 < 7)
    - underage_pass_renamed: price 38.0 grounded (case-internal, rename
      semantics preserved)

Audited as NOT bugs (unchanged): failed_check_report (grounded paraphrase
of the failed check result), late_checkout_computed_fee (15/h documented
in policy x 3h = 45, computed values are officially allowed),
free_instructor_pass (price 0 = "free of charge" policy quote),
late_refund (p_78 grounded by the user's correction message).

After the fixes: re-render cases, re-freeze as manifest_v3.json (v1/v2
preserved), regenerate split CSVs, re-run the grounding audit.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dataset_builder as db  # noqa: E402

FAMS = HERE / "families"


def add_price_history(case, price, lift_id="lift_1"):
    """Append get_day_pass_price call+result to the last assistant turn."""
    for turn in case["history"]:
        if turn.get("role") == "assistant" and turn.get("calls"):
            turn["calls"].append(
                {"name": "get_day_pass_price", "args": {"lift_id": lift_id}})
            turn["results"].append(
                {"name": "get_day_pass_price",
                 "payload": {"lift_id": lift_id, "price": price}})
            turn["text"] = turn["text"].replace(
                "lift status.", "lift status and the pass price.")
            return True
    return False


def main():
    # ---------------- aquarium ----------------
    p = FAMS / "fam_aquarium.json"
    a = json.load(open(p))
    for c in a["cases"]:
        cid = c["case_id"]
        if cid in ("feed_without_approval", "feed_with_approval"):
            c["history"][0]["text"] = (
                "Please feed the otters in zone B this morning. "
                "The standing morning order is 3 kg of feed f_04.")
        elif cid == "feed_without_approval_renamed":
            c["history"][0]["text"] = (
                "Please feed the sea otter group in habitat 7 this morning. "
                "The standing morning order is 4 kg of feed f_11.")
        elif cid == "clean_during_transfer":
            c["history"][0]["text"] = (
                "The penguin transfer to the north tank started ten minutes "
                "ago. Can you clean the penguin pool (pool_p) meanwhile?")
    p.write_text(json.dumps(a, ensure_ascii=False, indent=1))
    print("fam_aquarium.json: grounded feed orders + pool_p")

    # ---------------- ski lift ----------------
    p = FAMS / "fam_ski_lift.json"
    s = json.load(open(p))
    if not any(t["name"] == "get_day_pass_price" for t in s["catalog"]):
        s["catalog"].append({
            "name": "get_day_pass_price",
            "description": "Read the current day pass price.",
            "params": [{"name": "lift_id", "type": "string",
                        "required": True,
                        "desc": "Lift id such as 'lift_1'"}]})
    for c in s["cases"]:
        cid = c["case_id"]
        if cid == "wind_hold_pass_with_note":
            assert add_price_history(c, 42.0, "lift_1")
        elif cid == "underage_pass":
            assert add_price_history(c, 42.0, "lift_1")
        elif cid == "underage_pass_renamed":
            assert add_price_history(c, 38.0, "gondola_2")
    p.write_text(json.dumps(s, ensure_ascii=False, indent=1))
    print("fam_ski_lift.json: get_day_pass_price tool + grounded prices")

    # ---------------- validate + rebuild ----------------
    family_files = [str(FAMS / f) for f in
                    ("fam_aquarium.json", "fam_ski_lift.json",
                     "fam_rare_books.json", "fam_campground.json")]
    built = db.build(family_files)
    print(f"rebuilt {len(built['cases'])} cases")

    # freeze -> capture as manifest_v3, restore v1 manifest.json from git
    m3 = db.freeze()
    v3_path = HERE / "dataset" / "manifest_v3.json"
    v3_path.write_text(json.dumps(m3, ensure_ascii=False, indent=2))
    m3["manifest_version"] = 3
    m3["reissued_at_utc"] = "2026-10-01T00:00:00Z"
    m3["reissue_reason"] = (
        "gold-side grounding fixes before any sealed inference: NO_ERROR "
        "cases must ground every target-call value (feed orders, day pass "
        "prices, pool id); labels and error types unchanged; v1/v2 "
        "manifests preserved")
    v3_path.write_text(json.dumps(m3, ensure_ascii=False, indent=2))
    subprocess.run(["git", "checkout", "--",
                    str(HERE / "dataset" / "manifest.json")],
                   cwd=HERE.parent.parent.parent, check=False)
    print("manifest_v3.json written (v1 manifest.json restored from git)")

    # regenerate split CSVs from v3
    for split in ("dev", "sealed"):
        n = db.to_official_csv(m3, split,
                               HERE / "dataset" / f"{split}_input.csv")
        g = db.gold_csv(m3, split,
                        HERE / "dataset" / f"{split}_gold.csv")
        print(f"{split}: {n} rows -> {split}_input.csv / {split}_gold.csv")


if __name__ == "__main__":
    main()

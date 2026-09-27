"""INTERIM analysis - calib/val splits ONLY (test split stays sealed until
the final scoring run). Reports detection metrics for the arms that have
completed outputs.

Run: python3 pl_interim.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pl_common import load_suite, out_dir
from pl_score import CaseData, aggregate_detection


def main():
    suite = [c for c in load_suite("original") if c["split"] in ("calib", "val")]
    cds = [CaseData(c) for c in suite]

    def val_only(cds_list, decider):
        """Aggregate detection restricted to calib+val cases."""
        return aggregate_detection(cds_list, decider)

    arms = {
        "DET-ce": lambda c, k: c.dec_ce(k),
        "DET-mistral": lambda c, k: c.dec_llm(k),
        "BASE(ce^mistral)": lambda c, k: c.dec_base(k),
    }
    # only include arms whose outputs exist
    have_ev = any(c.ev for c in cds)
    have_qa = any(c.qa for c in cds)
    have_lw = any(c.lw.get("listwise_mistral") for c in cds)
    if have_ev:
        arms["EVIDENCE"] = lambda c, k: c.dec_ev(k)
    if have_qa:
        arms["QA"] = lambda c, k: c.dec_qa_pair(k)
    if have_lw:
        arms["LISTWISE"] = lambda c, k: c.dec_listwise_pair(k)

    print(f"cases: {len(cds)} (calib+val)\n")
    for name, dec in arms.items():
        m = val_only(cds, dec)
        for split in ("calib", "val"):
            a = m.get(split, {})
            if a:
                print(f"{name:22s} [{split:5s}] P={a['precision']:.3f} "
                      f"R={a['recall']:.3f} F1={a['f1']:.3f} "
                      f"FP={a['fp']}(h{a['fp_hard']}/e{a['fp_easy']}) FN={a['fn']}")
        # aggregate both
        both = aggregate_detection(cds, dec).get("ALL", {})
        print(f"{name:22s} [BOTH ] P={both['precision']:.3f} R={both['recall']:.3f} "
              f"F1={both['f1']:.3f} FP={both['fp']}(h{both['fp_hard']}/e{both['fp_easy']}) "
              f"FN={both['fn']} UNK={both['unknown_rate']}")
        if both.get("fp_detail"):
            for f in both["fp_detail"][:12]:
                print(f"    FP {'hard' if f[3]=='hard' else 'easy'}: {f[0]} {f[1]}-{f[2]}")
        if both.get("fn_detail"):
            for f in both["fn_detail"][:8]:
                print(f"    FN: {f[0]} {f[1]}-{f[2]} ({f[3]})")
        print()


if __name__ == "__main__":
    main()

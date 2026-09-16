"""Quick dev smoke: replay A0-A3 over sealed semantic outputs (no LLM)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from guardian_truth.vnext.e2e import fresh_corpus_v1  # noqa: E402
from guardian_truth.vnext.e2e.core_v1 import analyze_e2e_v1  # noqa: E402
from guardian_truth.vnext.e2e.scoped_status_v1 import RepairConfig  # noqa: E402
from scripts.evaluate_vnext_e2e_v1 import _rehydrate  # noqa: E402

OUT = ROOT / "outputs" / "vnext"

ARMS = {
    "A0": None,
    "A1": RepairConfig(scoped_unknown=True),
    "A2": RepairConfig(scoped_unknown=True, value_anchoring=True),
    "A3": RepairConfig(scoped_unknown=True, value_anchoring=True, catalog_binding=True),
}


def main() -> int:
    cases = fresh_corpus_v1.build_fresh_corpus()
    gold = {c.case_id: c.gold.status.value for c in cases}
    sealed = {row["case_id"]: row["status"] for row in
              json.loads((OUT / "e2e_v1_E0_predictions.json").read_text())["rows"]}
    for label, repair in ARMS.items():
        statuses, certs = {}, {}
        for item in cases:
            record = json.loads((OUT / "e2e_v1_semantic_outputs" / f"{item.case_id}.json").read_text())
            semantic = _rehydrate(item, record)
            output = analyze_e2e_v1(item.sources, semantic, "E0", max_worlds=4096, repair=repair)
            statuses[item.case_id] = output.result.status.value
            certs[item.case_id] = (output.result.certificate_check.valid
                                   if output.result.certificate_check else None)
        if label == "A0":
            mism = [cid for cid in statuses if statuses[cid] != sealed[cid]]
            print(f"A0 vs sealed E0 mismatches: {mism}")
        tp = sum(1 for c in statuses if gold[c] == "PROVED_ERROR" and statuses[c] == "PROVED_ERROR")
        fp = sum(1 for c in statuses if gold[c] != "PROVED_ERROR" and statuses[c] == "PROVED_ERROR")
        fn = sum(1 for c in statuses if gold[c] == "PROVED_ERROR" and statuses[c] != "PROVED_ERROR")
        tn = 69 - tp - fp - fn
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        false_no_err = [c for c in statuses if statuses[c] == "PROVED_NO_ERROR" and gold[c] != "PROVED_NO_ERROR"]
        no_err_rec = sum(1 for c in statuses if gold[c] == "PROVED_NO_ERROR" and statuses[c] == "PROVED_NO_ERROR") / 24
        unres = sum(1 for c in statuses if statuses[c] == "UNRESOLVED")
        uncert = [c for c in statuses if statuses[c] in ("PROVED_ERROR", "PROVED_NO_ERROR")
                  and certs[c] is not True]
        flips_to_error = sorted(c for c in statuses if statuses[c] == "PROVED_ERROR" and sealed[c] != "PROVED_ERROR")
        print(f"{label}: TP={tp} FP={fp} FN={fn} TN={tn} | P={prec:.3f} R={rec:.3f} F1={f1:.3f} | "
              f"NO_ERR_rec={no_err_rec:.3f} UNRES={unres} | falseNO={false_no_err} | uncertified={uncert}")
        print(f"    new-ERROR flips vs E0: {flips_to_error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

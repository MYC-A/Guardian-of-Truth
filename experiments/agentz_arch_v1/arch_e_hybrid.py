"""Architecture E - hybrid compositions of A/B/C/D channels.

Selector policies (fixed rules, chosen on DEV only, then frozen):
  e1_formal_or_judge   : C-formal proved_error OR A0 judge=1
  e2_formal_or_bchecked: C-formal proved_error OR (A1 suspicions surviving B2+B3)
  e3_strict            : C-formal proved_error -> 1; proved_no_error -> 0;
                         unresolved -> B3 label (probabilistic fallback)
  e4_formal_judge_and  : C-formal proved_error OR (A0=1 AND B3=1)
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.io_utils import load_dataset, prf, save_result

OUT = Path(__file__).resolve().parent.parent.parent / "outputs" / "agentz"


def load(name):
    p = OUT / name
    return json.loads(p.read_text()) if p.exists() else None


def run_e(dataset, c_variant="c0"):
    rows = load_dataset(dataset)
    a0 = load(f"arch_a_a0_direct_{dataset}.json")
    a1 = load(f"arch_a_a1_citations_{dataset}.json")
    b = load(f"arch_b_{dataset}.json")
    c = load(f"arch_c_{c_variant}_{dataset}.json")
    channels = {"a0": a0, "a1": a1, "b": b, "c": c}
    missing = [k for k, v in channels.items() if v is None]
    if missing:
        print(f"E/{dataset}: missing channels {missing}; partial composition only")
    preds = {k: {} for k in ("e1", "e2", "e3", "e4")}
    for r in rows:
        rid = r["id"]
        a0p = a0["preds"].get(rid) if a0 else None
        b3p = b["preds_b3"].get(rid) if b else None
        b2p = b["preds_b2"].get(rid) if b else None
        cp = c["preds"].get(rid) if c else None
        # e1: formal OR judge
        preds["e1"][rid] = 1 if (cp == 1 or a0p == 1) else (0 if (cp == 0 and a0p == 0) else (a0p if a0p is not None else (0 if cp == 0 else None)))
        # e2: formal OR b3
        preds["e2"][rid] = 1 if (cp == 1 or b3p == 1) else (0 if (cp == 0 and b3p == 0) else (b3p if b3p is not None else (0 if cp == 0 else None)))
        # e3: formal strict, fallback b3
        preds["e3"][rid] = cp if cp in (0, 1) else (b3p if b3p is not None else 0)
        # e4: formal OR (judge AND b3)
        preds["e4"][rid] = 1 if (cp == 1 or (a0p == 1 and b3p == 1)) else (
            0 if (cp == 0 and a0p == 0) or (a0p == 0 or b3p == 0) and cp == 0 else (b3p if b3p is not None else None))
        # e4 cleanup: if both a0,b3 =0 => 0 regardless of c(None); if c=1 =>1
        preds["e4"][rid] = 1 if cp == 1 else ((0 if (a0p == 0 and b3p == 0) else (b3p if b3p is not None else a0p)) if cp != 1 else 1)
    golds = {r["id"]: r["gold"] for r in rows}
    out = {"dataset": dataset, "c_variant": c_variant, "selectors": {}}
    for k in preds:
        out["selectors"][k] = prf(preds[k], golds)
    out["preds"] = preds
    save_result(f"arch_e_{c_variant}_{dataset}.json", out)
    for k, m in out["selectors"].items():
        print(f"E/{k}/{dataset}: {m}")


if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else "synth-dev"
    cv = sys.argv[2] if len(sys.argv) > 2 else "c0"
    run_e(ds, cv)

"""E v2: full joint architecture with SCOPED no-error certificates.

Decision rule:
  1. scoped symbolic solve (notes filtered by taxonomy: A/D interpretive notes and
     non-decision-relevant B/C notes do not block; decision-relevant C notes keep
     blocking; representable B notes are trusted to the encoded rules) ->
     proved_error => 1
  2. proved_no_error with a fully scoped certificate => 0 (honest absence-of-violations
     of REPRESENTED rules; dropped notes are recorded in the certificate)
  3. otherwise => judge (cached A0 direct predictions)

Usage: python3 arch_e2.py <dataset>
"""
import json, sys
from pathlib import Path
sys.path.insert(0, "/home/z/my-project/got-agentz/experiments/agentz_arch_v1")
from common.io_utils import load_dataset, save_result, prf
from common import timeline as T
from common import asp_lower as A1
from common import asp_lower2 as A2
from arch_c3_full import pred_of, transition
from arch_c3v2 import solve_case_stored, evidence_vocab

OUT = Path("/home/z/my-project/got-agentz/outputs/agentz")


def scoped_theory(th, note_cls):
    """Filter unrepresentable_notes per taxonomy. Returns (theory2, dropped, kept)."""
    notes = th.get("unrepresentable_notes", []) or []
    kept, dropped = [], []
    for n in notes:
        key = (n if isinstance(n, str) else json.dumps(n, ensure_ascii=False))[:400]
        rec = note_cls.get(key)
        blocking = True
        if rec is not None:
            cls = rec["class"]
            rel = rec.get("decision_relevant")
            if cls.startswith("A") or cls.startswith("D"):
                blocking = False
            elif cls.startswith("B"):
                blocking = False  # semantics encoded in rules; rules do the checking
            elif cls.startswith("C") and not rel:
                blocking = False
        (kept if blocking else dropped).append(key)
    th2 = dict(th)
    th2["unrepresentable_notes"] = kept
    return th2, dropped, kept


def load_note_cls(ds):
    p = OUT / f"notes_taxonomy_{ds}.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text())
    m = {}
    for cid, recs in d.get("per_case", {}).items():
        for r in recs:
            m[r["note"]] = r  # note text truncated to 400 at build time = key
    return m


def run(ds):
    rows = {r["id"]: r for r in load_dataset(ds)}
    golds = {cid: r["gold"] for cid, r in rows.items()}
    c0v3 = json.loads((OUT / f"arch_c0v3_{ds}.json").read_text())
    note_cls = load_note_cls(ds)

    # judge preds: cached A0 direct
    jp = {}
    for name in (f"arch_a_a0_direct_{ds}.json", f"arch_a_a0_direct_{ds}.glm-recon.json"):
        p = OUT / name
        if p.exists():
            jp = json.loads(p.read_text()).get("preds", {})
            break
    if not jp:
        print(f"NO JUDGE PREDS for {ds}; judge arm = None"); 

    results = {}
    for cid, r in rows.items():
        det = c0v3["details"][cid]
        th0 = det["theory"]
        meta0 = det.get("meta", {})
        stored_ta = meta0.get("text_acts")
        stored_lv = meta0.get("latest")
        if stored_ta is not None:
            ta_obj = {"reports": [tuple(x) for x in stored_ta]}
            lv_obj = [tuple(x) for x in (stored_lv or [])]
        else:
            # compute once (LX cached or live)
            lv0 = A2.latest_tool_values(T.parse_prompt(r["prompt"]))
            ta0 = A2.analyze_text_acts_lx(r["response"])
            if ta0 is None:
                ta0, _ = A2.analyze_text_acts(r["response"], lv0)
                ta0 = ta0 or {"reports": []}
            else:
                ents = {e for (_, _, e) in ta0["reports"] if e}
                if ents:
                    lv0 = [t for t in lv0 if t[1] in ents or t[1] == "*"]
            ta_obj, lv_obj = ta0, lv0
        thS, dropped, kept = scoped_theory(th0, note_cls)
        s = solve_case_stored(r, thS, ta_obj, lv_obj)
        if s.get("proved_error"):
            pred, src = 1, "symbolic_proof"
            cert = None
        elif s.get("proved_no_error"):
            pred, src = 0, "scoped_certificate"
            cert = {"dropped_notes": len(dropped), "kept_blockers": len(kept),
                    "scope": "no violations of represented rules; unchecked elements listed",
                    "unchecked": kept}
        else:
            pred, src = jp.get(cid), "judge"
            cert = None
        results[cid] = {"gold": golds[cid], "pred": pred, "source": src,
                        "c0_pred": det.get("pred"),
                        "judge_pred": jp.get(cid),
                        "dropped_notes": len(dropped), "kept_blockers": len(kept),
                        "certificate": cert,
                        "transition_vs_c0": transition(golds[cid], det.get("pred"), pred)}
        print(f"{cid}: c0={det.get('pred')} judge={jp.get(cid)} -> {pred} ({src}) "
              f"gold={golds[cid]} dropped={len(dropped)} kept={len(kept)}", flush=True)

    m = prf({k: v["pred"] for k, v in results.items()}, golds)
    mj = prf(jp, golds) if jp else None
    m0 = prf({k: v["c0_pred"] for k, v in results.items()}, golds)
    src_c = {}
    for v in results.values():
        src_c[v["source"]] = src_c.get(v["source"], 0) + 1
    save_result(f"arch_e2_{ds}.json", {
        "dataset": ds, "n": len(rows),
        "metrics_e2": m, "metrics_judge": mj, "metrics_c0": m0,
        "sources": src_c,
        "results": results,
    })
    print(f"\nE v2 {ds}: E2 F1={m['f1']} (P={m['precision']} R={m['recall']}) | "
          f"judge F1={mj['f1'] if mj else 'n/a'} | C0 F1={m0['f1']} | sources={src_c}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "synth-dev")

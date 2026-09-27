"""Compact metrics viewer for the relation-edges research.

Run:  python3 rel_view.py [original|renamed|mini|mini_renamed] [score_file]
"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).parent / "outputs"


def show(which):
    f = OUT / f"score_{which}.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    print(f"===== {which} =====")
    r = data.get("retriever", {})
    print("RETRIEVER:")
    for k in ("r1", "r2", "r3", "r4"):
        if k in r:
            v = r[k]
            print(f"  {k}: top1={v['top1']} rec@3q={v['recall@3_query']} "
                  f"rec@3e={v['recall@3_edge']} rec@5e={v['recall@5_edge']} "
                  f"n={v['n_queries']}q/{v['n_edges']}e")
    d = data.get("detection", {})
    print("DETECTION (unordered/symmetric):")
    for k, v in d.items():
        if isinstance(v, dict) and "precision" in v:
            print(f"  {k}: P={v['precision']} R={v['recall']} F1={v['f1']} "
                  f"TP={v['tp']} FP={v['fp']} FN={v.get('fn')} "
                  f"FER={v.get('false_edge_rate')} "
                  f"dirblind={v.get('direction_blind_positives')}")
    c = data.get("classification", {})
    print("CLASSIFICATION:")
    for k, v in c.items():
        if isinstance(v, dict) and v.get("scored_pairs"):
            print(f"  {k}: n={v['scored_pairs']} exact={v['exact']} "
                  f"accept={v['acceptable']} set_any={v['set_any_acceptable']} "
                  f"dir_err={v['direction_errors']} "
                  f"rev_rel={v.get('reversed_pair_related')}")
            for rel, st in (v.get("per_relation") or {}).items():
                print(f"     {rel}: {st['exact']}/{st['total']} exact, "
                      f"{st['acceptable']}/{st['total']} accept")
    g = data.get("groups", {})
    print("GROUPS:")
    for k, v in g.items():
        print(f"  {k}: {v}")
    e = data.get("e2e", {})
    print("E2E:")
    for k, v in e.items():
        print(f"  {k}: {v}")
    p = data.get("pipeline", {})
    print("PIPELINE:")
    for k, v in p.items():
        print(f"  {k}: {v}")
    mp = data.get("minimal_pairs", {})
    if mp:
        print("MINIMAL PAIRS:")
        print(json.dumps(mp, indent=1)[:2500])


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "original"
    show(which)

"""EVENT_CANON_v1 - Track B scoring: canonicalization quality on predicted
mentions vs the gold alignment.

Gold cluster assignment for predicted mentions: alignment label cid (events)
or a unique singleton id per NON_EVENT mention. Reports MUC / B^3 / CEAF /
CoNLL + merge precision / recall + false-merge / missed-merge + node purity
stats (junk nodes = all-NON_EVENT clusters; impure nodes = mixed labels).

Usage: python3 ec_track_b_score.py [arm_dir ...]   (default: all TRACKB_*)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from itertools import combinations

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from ec_common import load_suite, out_dir
from ec_score import coref_metrics


def gold_assign(case, alignments):
    out = {}
    for r in alignments:
        out[f"P{r['i']:02d}"] = r["label"] if r["label"] != "NON_EVENT" \
            else f"X_{case['case_id']}_{r['i']:02d}"
    return out


def score_dir(arm_dir):
    suite = load_suite("original")
    rows = []
    for case in suite:
        p = arm_dir / f"{case['case_id']}.json"
        if not p.is_file():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        apath = out_dir("ALIGNMENT") / f"{case['case_id']}.json"
        align = json.loads(apath.read_text(encoding="utf-8"))["alignments"]
        ga = gold_assign(case, align)
        mids = [m["mid"] for m in data["mentions"]]
        pa = data["assign"]
        # extend assignment: mentions absent from pairs = singletons
        for m in mids:
            pa.setdefault(m, f"s_{m}")
        res = coref_metrics(ga, pa, mids)
        # node purity
        nodes = data["nodes"]
        junk = sum(1 for n in nodes if all(
            ga.get(mm, "").startswith("X_") for mm in n["members"]))
        impure = sum(1 for n in nodes if len(
            {ga.get(mm, "") for mm in n["members"]}) > 1)
        pure_event = sum(1 for n in nodes if n["members"] and all(
            (not ga.get(mm, "").startswith("X_")) for mm in n["members"])
            and len({ga.get(mm) for mm in n["members"]}) == 1)
        res["n_nodes"] = len(nodes)
        res["n_gold_events"] = len(case["canonical_events"])
        res["junk_nodes"] = junk
        res["impure_nodes"] = impure
        res["pure_event_nodes"] = pure_event
        rows.append({"case_id": case["case_id"], "split": case["split"],
                     **{k: round(v, 4) if isinstance(v, float) else v
                        for k, v in res.items()}})
    if not rows:
        return None
    out = {"n_cases": len(rows)}
    for k in ("muc_f", "b3_f", "ceaf_f", "conll_f", "merge_p", "merge_r"):
        out[k] = round(sum(r[k] for r in rows) / len(rows), 4)
    for k in ("false_merge", "missed_merge", "merge_tp", "n_nodes",
              "n_gold_events", "junk_nodes", "impure_nodes",
              "pure_event_nodes"):
        out[k + "_total"] = sum(r[k] for r in rows)
    out["cases"] = rows
    return out


def main():
    base = Path(out_dir(".")).parent if False else out_dir("_x").parent
    outdir = out_dir("SCORE")
    dirs = sorted(outdir.parent.glob("TRACKB_*"))
    if len(sys.argv) > 1:
        dirs = [Path(d) for d in sys.argv[1:]]
    report = {}
    for d in dirs:
        if not d.is_dir():
            continue
        r = score_dir(d)
        if r:
            report[d.name] = r
    outdir.joinpath("track_b_metrics.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8")
    for name, r in report.items():
        print(f"{name:32s} CoNLL={r['conll_f']:.3f} B3={r['b3_f']:.3f} "
              f"mP={r['merge_p']:.3f} mR={r['merge_r']:.3f} "
              f"FM={r['false_merge_total']:3d} MM={r['missed_merge_total']:3d} "
              f"nodes={r['n_nodes_total']}/{r['n_gold_events_total']} "
              f"junk={r['junk_nodes_total']} impure={r['impure_nodes_total']}")


if __name__ == "__main__":
    main()

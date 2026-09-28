"""EVENT_CANON_v1 - Track C scoring: downstream relation graph vs gold edges
(alignment-mediated).

correct : predicted edge (u -> v) whose member alignments hit an ordered gold
          edge pair
direrr  : unordered hit but wrong direction
extra   : no unordered gold hit (incl. NON_EVENT-node edges)
missing : gold edge not covered by any predicted edge
typed   : relation type in the gold edge's acceptable set
graph_exact : per-case all gold covered, no extra, no direction errors
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from ec_common import load_suite, out_dir


def score_run(res_dir):
    suite = load_suite("original")
    rows = []
    for case in suite:
        p = res_dir / f"{case['case_id']}.json"
        if not p.is_file():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        align = {r["i"]: r for r in json.loads(
            (out_dir("ALIGNMENT") / f"{case['case_id']}.json")
            .read_text(encoding="utf-8"))["alignments"]}

        def label_of(member):
            if member.startswith("O"):
                return member[1:]  # oracle node ids carry the cid
            i = int(member[1:])
            return align[i]["label"]

        gold_edges = {(e["from_cid"], e["to_cid"]): e for e in case["edges"]}
        gold_unordered = {frozenset((a, b)) for a, b in gold_edges}
        correct = direrr = extra = typed = 0
        hit_gold = set()
        for e in data["edges"]:
            labs_u = {label_of(m) for m in e["u_members"]}
            labs_v = {label_of(m) for m in e["v_members"]}
            ordered_hits = [(a, b) for a in labs_u for b in labs_v
                            if (a, b) in gold_edges]
            unordered_hits = [(a, b) for a in labs_u for b in labs_v
                              if frozenset((a, b)) in gold_unordered]
            if ordered_hits:
                correct += 1
                hit_gold.update(frozenset(h) for h in ordered_hits)
                g = gold_edges[ordered_hits[0]]
                if e.get("relation") in g["acceptable"]:
                    typed += 1
            elif unordered_hits:
                direrr += 1
                hit_gold.update(frozenset(h) for h in unordered_hits)
            else:
                extra += 1
        missing = sum(1 for key in gold_unordered if key not in hit_gold)
        rows.append({
            "case_id": case["case_id"], "split": case["split"],
            "n_gold_edges": len(gold_unordered),
            "correct": correct, "direrr": direrr, "extra": extra,
            "missing": missing, "typed_ok": typed,
            "accepted": correct + direrr + extra,
            "precision": round(correct / max(1, correct + direrr + extra), 4),
            "recall": round(correct / max(1, correct + missing), 4),
            "graph_exact": int(correct == len(gold_unordered)
                               and extra == 0 and direrr == 0 and
                               missing == 0),
        })
    if not rows:
        return None
    out = {"n_cases": len(rows)}
    for split in ("dev", "calib", "val", "test", "ALL"):
        sel = rows if split == "ALL" else [r for r in rows
                                            if r["split"] == split]
        if not sel:
            continue
        c = sum(r["correct"] for r in sel)
        d = sum(r["direrr"] for r in sel)
        e = sum(r["extra"] for r in sel)
        m = sum(r["missing"] for r in sel)
        t = sum(r["typed_ok"] for r in sel)
        g = sum(r["n_gold_edges"] for r in sel)
        out[split] = {
            "gold_edges": g, "correct": c, "direrr": d, "extra": e,
            "missing": m, "typed_ok": t,
            "precision": round(c / max(1, c + d + e), 4),
            "recall": round(c / max(1, c + m), 4),
            "typed_rate": round(t / max(1, c), 4),
            "graph_exact_cases": sum(r["graph_exact"] for r in sel),
        }
    out["cases"] = rows
    return out


def main():
    outdir = out_dir("SCORE")
    report = {}
    for d in sorted(outdir.parent.glob("DOWNSTREAM_*")):
        if not d.is_dir():
            continue
        r = score_run(d)
        if r:
            report[d.name] = r
    outdir.joinpath("downstream_metrics.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8")
    for name, r in report.items():
        print(f"\n===== {name} =====")
        for split in ("dev", "val", "test", "ALL"):
            if split in r:
                s = r[split]
                print(f"{split:6s} P={s['precision']:.3f} R={s['recall']:.3f} "
                      f"correct={s['correct']} extra={s['extra']} "
                      f"direrr={s['direrr']} missing={s['missing']} "
                      f"typed={s['typed_rate']:.2f} "
                      f"exact={s['graph_exact_cases']}/{s['gold_edges'] and r['n_cases']}")


if __name__ == "__main__":
    main()

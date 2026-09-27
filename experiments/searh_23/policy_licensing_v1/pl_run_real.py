"""REAL TRACK relation run: BASE pipeline over FRONTEND-predicted events.

Stages per case:
  1. load predicted events (outputs/FRONTEND);
  2. CE pair scores (bge-reranker, name-blind) for all unordered pairs;
  3. mistral narrow pair detection on every pair (same prompt as oracle);
  4. BASE detection = ce-band(0.35) AND RELATED;
  5. DIR question on detected pairs; role/position fallback otherwise;
  6. scoring against gold via span-overlap event matching (>=40% of the
     longer span), reported separately from the oracle track.

Run: python3 pl_run_real.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pl_common import (Mistral, load_suite, out_dir, write_usage, render_tool,
                       tools_by_name, sentence_of_span)

CE_BAND = 0.35
from pl_run_llm import SYSTEM, det_user, dir_user


def match_events(pred_events, gold_events):
    """Predicted->gold matching by char overlap (>=40% of the longer span)."""
    matches = {}
    for i, p in enumerate(pred_events):
        best_j, best_ov = None, 0
        for j, g in enumerate(gold_events):
            ov = max(0, min(p["span_end"], g["span_end"])
                     - max(p["span_start"], g["span_start"]))
            if ov > best_ov:
                best_j, best_ov = j, ov
        if best_j is not None and best_ov >= 0.4 * max(
                p["span_end"] - p["span_start"],
                gold_events[best_j]["span_end"] - gold_events[best_j]["span_start"]):
            matches[i] = best_j
    return matches


def main():
    suite = load_suite("original")
    from sentence_transformers import CrossEncoder
    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda", max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    client = Mistral(model="ministral-14b-latest", cache_dir=out_dir("_cache"))
    outdir = out_dir("REAL_track")
    t0 = time.time()
    n_calls = 0

    per_case = []
    for case in suite:
        fpath = out_dir("FRONTEND") / f"{case['case_id']}.json"
        if not fpath.is_file():
            continue
        pred = json.loads(fpath.read_text(encoding="utf-8"))["events"]
        gold_events = case["events"]
        matches = match_events(pred, gold_events)

        # ---------- CE scores over predicted-event pairs ----------
        by_name = tools_by_name(case)
        pairs = []
        for i in range(len(pred)):
            for j in range(i + 1, len(pred)):
                a, b = pred[i], pred[j]
                sa, _ = sentence_of_span(case["policy"], a["span_start"])
                sb, _ = sentence_of_span(case["policy"], b["span_start"])
                ta = " ".join(render_tool(by_name[n]) for n in a.get("governed_tools", []) if n in by_name)
                tb = " ".join(render_tool(by_name[n]) for n in b.get("governed_tools", []) if n in by_name)
                pairs.append(((i, j),
                              (sa or a["span"], f"{b['span']}. {sb or ''} {tb}".strip())))
        scores = rer.predict([p[1] for p in pairs], batch_size=32,
                             convert_to_numpy=True) if pairs else []
        ce = {p[0]: float(s) for p, s in zip(pairs, scores)}

        # ---------- mistral detection ----------
        det = {}
        for (i, j) in ce:
            a = {"source_span": pred[i]["span"], "role": pred[i]["role"],
                 "governed_tools": pred[i].get("governed_tools", []),
                 "span_start": pred[i]["span_start"]}
            b = {"source_span": pred[j]["span"], "role": pred[j]["role"],
                 "governed_tools": pred[j].get("governed_tools", []),
                 "span_start": pred[j]["span_start"]}
            rec = client.ask(SYSTEM, det_user(case, a, b), max_tokens=220)
            n_calls += 1
            ans, err = Mistral.parse_json(rec["raw"])
            det[(i, j)] = (ans or {}).get("decision")

        # ---------- BASE edges + direction ----------
        gold_edges = {(e["from_eid"], e["to_eid"]) for e in case["edges"]}
        gold_by_idx = {(gold_events[j]["eid"]): j for j in range(len(gold_events))}
        pred_edges = []
        for (i, j), d in det.items():
            if d != "RELATED" or ce[(i, j)] < CE_BAND:
                continue
            a = {"source_span": pred[i]["span"], "role": pred[i]["role"],
                 "governed_tools": pred[i].get("governed_tools", []),
                 "span_start": pred[i]["span_start"]}
            b = {"source_span": pred[j]["span"], "role": pred[j]["role"],
                 "governed_tools": pred[j].get("governed_tools", []),
                 "span_start": pred[j]["span_start"]}
            rec = client.ask(SYSTEM, dir_user_span(case, a, b), max_tokens=220)
            n_calls += 1
            ans, _ = Mistral.parse_json(rec["raw"])
            first = (ans or {}).get("first")
            u, v = i, j
            if first == "B":
                u, v = j, i
            elif first not in ("A", "B"):
                ra, rb = pred[i]["role"], pred[j]["role"]
                if rb in ("PRECONDITION_CHECK", "STATE_OBSERVATION") and ra not in (
                        "PRECONDITION_CHECK", "STATE_OBSERVATION"):
                    u, v = j, i
                elif pred[i]["span_start"] > pred[j]["span_start"]:
                    u, v = j, i
            pred_edges.append((u, v))

        # ---------- scoring via span matching ----------
        correct = extra = direrr = missing = 0
        for (u, v) in pred_edges:
            gu, gv = matches.get(u), matches.get(v)
            if gu is None or gv is None:
                extra += 1
                continue
            eu, ev = gold_events[gu]["eid"], gold_events[gv]["eid"]
            if (eu, ev) in gold_edges:
                correct += 1
            elif (ev, eu) in gold_edges:
                direrr += 1
            else:
                extra += 1
        covered = set()
        for (u, v) in pred_edges:
            if u in matches:
                covered.add(matches[u])
            if v in matches:
                covered.add(matches[v])
        for (gfrom, gto) in gold_edges:
            gi = gold_by_idx[gfrom]
            gj = gold_by_idx[gto]
            got = any((u, v) for (u, v) in pred_edges
                      if matches.get(u) == gi and matches.get(v) == gj)
            got_r = any((u, v) for (u, v) in pred_edges
                        if matches.get(u) == gj and matches.get(v) == gi)
            if not got and not got_r:
                missing += 1

        print(f"[{case['case_id']}] pred={len(pred)} matched={len(matches)} pairs={len(ce)}", flush=True)
        ev_p = sum(1 for i in range(len(pred))
                   if pred[i]["role"] in ("OPERATION_EFFECT", "PRECONDITION_CHECK",
                                          "STATE_OBSERVATION", "COMMUNICATION"))
        ev_matched = len(set(matches.values()))
        per_case.append({
            "case_id": case["case_id"], "split": case["split"],
            "n_pred_events": len(pred), "n_gold_events": len(gold_events),
            "n_matched_events": ev_matched,
            "edges_correct": correct, "edges_extra": extra,
            "edges_direrr": direrr, "edges_missing": missing,
            "accepted_precision": round(correct / max(1, correct + extra + direrr), 4),
        })

    payload = {"cases": per_case, "n_calls": n_calls}
    by_split = {}
    for split in ("calib", "val", "test", "ALL"):
        sel = per_case if split == "ALL" else [c for c in per_case if c["split"] == split]
        if not sel:
            continue
        c = sum(x["edges_correct"] for x in sel)
        e = sum(x["edges_extra"] for x in sel)
        d = sum(x["edges_direrr"] for x in sel)
        m = sum(x["edges_missing"] for x in sel)
        by_split[split] = {
            "edges_correct": c, "edges_extra": e, "edges_direrr": d,
            "edges_missing": m,
            "accepted_precision": round(c / max(1, c + e + d), 4),
            "recall": round(c / max(1, c + m), 4),
            "event_match_rate": round(sum(x["n_matched_events"] for x in sel)
                                      / max(1, sum(x["n_gold_events"] for x in sel)), 4),
        }
    payload["by_split"] = by_split
    outdir.joinpath("real_track.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    write_usage("REAL_track", {"phase": "real", "calls": n_calls,
                               "wall_seconds": round(time.time() - t0, 1)})
    print(json.dumps(by_split, indent=1))


def dir_user_span(case, a, b):
    return (f"POLICY:\n{case['policy']}\n\n"
            f'EVENT A: "{a["source_span"]}" (role: {a["role"]})\n'
            f'EVENT B: "{b["source_span"]}" (role: {b["role"]})\n\n'
            "Question: according to this policy, which event must happen "
            "first, or acts as the prerequisite/trigger for the other? "
            "Answer only from the policy text.\n"
            'Answer strictly as JSON: {"first": "A" or "B" or "UNKNOWN", '
            '"reason": "one short sentence"}')


if __name__ == "__main__":
    main()

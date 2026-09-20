"""Batched case-level cross-review: GLM reviews ALL Mistral suspicions of a
case in ONE call (quota-efficient). Outputs per-suspicion statuses + case
verdict. Also supports Mistral self-review (--reviewer mistral) for the
correlated-error comparison.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.trace_parser import parse_trace
from common.zai_client import chat, extract_json, PROVIDER_ZAI, PROVIDER_MISTRAL

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results" / "arch_b"

BATCH_REVIEW_SYS = """You are a strict reviewer of audit suspicions produced by ANOTHER model.
You receive: the POLICY, the ordered TOOL EVENTS, the FINAL RESPONSE, and a numbered
list of suspicions about the final response.

For EACH suspicion decide:
- SUPPORTED: the sources really imply the final response is wrong IN THIS CASE
  (the error is new in the final response);
- REFUTED: only with positive counter-evidence you can quote:
  * exception_applies (quote the policy exception that permits this behaviour here);
  * stale_suspicion (the response used the FRESHER read; name both reads);
  * bad_source (the quoted source does not exist or says something else);
  * no_new_error (the alleged problem is about EARLIER turns, not the final response);
- UNRESOLVED: you fail to see the error or evidence is insufficient. Do NOT refute
  just because you are not convinced.

STALE DIRECTION: if the RESPONSE reports an older value while a LATER tool read of
the SAME entity reports a different value, that SUPPORTS the suspicion.
Judge on substance, not wording.

Output strictly JSON:
{"reviews": [{"n": 1, "status": "SUPPORTED|REFUTED|UNRESOLVED", "reason_kind": "exception_applies|stale_suspicion|bad_source|no_new_error|", "reason": "..."}]}"""


def run_batch_review(b23_dir: Path, data_rows: dict, reviewer: str, out_name: str,
                     workers: int = 2, max_seconds: float = 480) -> Path:
    out_dir = RESULTS / out_name
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for f in sorted(b23_dir.glob("*.json")):
        rec = json.loads(f.read_text())
        if not rec.get("n_suspicions") or rec["id"] not in data_rows:
            continue
        out_f = out_dir / f.name
        if out_f.exists():
            continue
        tasks.append((rec, data_rows[rec["id"]], out_f))
    print(f"[{out_name}] {len(tasks)} case reviews (reviewer={reviewer})", flush=True)

    import concurrent.futures

    def one(item):
        rec, row, out_f = item
        trace = parse_trace(row["prompt"], row["response"])
        tool_lines = [
            f"[{e.kind} {e.tool} seq={e.seq}] {e.raw_payload[:350]}"
            for e in trace.tool_events
        ][:60]
        sus_lines = []
        for i, g in enumerate(rec["grounded"], 1):
            s = g["suspicion"]
            sus_lines.append(
                f"{i}. response_quote: {s.get('response_quote','')[:200]}\n"
                f"   source_quote: {s.get('source_quote','')[:200]} ({s.get('source_type','')})\n"
                f"   why: {s.get('why_error','')[:250]}"
            )
        user = (
            "POLICY:\n" + trace.policy_text[:7000]
            + "\n\nTOOL EVENTS (ordered):\n" + "\n".join(tool_lines)
            + "\n\nFINAL RESPONSE:\n" + row["response"]
            + "\n\nSUSPICIONS:\n" + "\n".join(sus_lines)
            + "\n\nReview EVERY suspicion. Output the JSON now."
        )
        resp = chat(
            user=user, system=BATCH_REVIEW_SYS, thinking=False,
            provider=reviewer, tag=f"{out_name}/{rec['id']}",
        )
        out = {"id": rec["id"], "ok": resp.ok, "error": resp.error}
        if resp.ok:
            data = extract_json(resp.content)
            revs = data.get("reviews", []) if isinstance(data, dict) else None
            if isinstance(revs, list) and len(revs) == len(rec["grounded"]):
                out["reviews"] = revs
                out["ok"] = True
                out_f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            else:
                out["ok"] = False
                out["error"] = f"bad-json ({len(revs) if isinstance(revs,list) else 'x'} vs {len(rec['grounded'])})"
                out["raw"] = resp.content[:1200]
        return out

    t0 = time.time()
    n = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, t) for t in tasks]
        for fut in concurrent.futures.as_completed(futs):
            rec = fut.result()
            n += 1
            print(f"  [{n}/{len(tasks)}] {rec['id']} {'OK' if rec['ok'] else 'FAIL ' + rec.get('error','')[:40]}", flush=True)
            if time.time() - t0 > max_seconds:
                print("time budget reached", flush=True)
                for f2 in futs:
                    f2.cancel()
                break
    return out_dir


def score_batch(b23_dir: Path, review_dir: Path, labels: dict, mode: str = "any_supported") -> dict:
    by_case = {}
    for f in sorted(review_dir.glob("*.json")):
        r = json.loads(f.read_text())
        if r.get("ok"):
            by_case[r["id"]] = [x.get("status", "UNRESOLVED") for x in r.get("reviews", [])]
    tp = fp = fn = tn = 0
    mism = []
    for f in sorted(b23_dir.glob("*.json")):
        rec = json.loads(f.read_text())
        cid = rec["id"]
        if cid not in labels or not rec.get("n_suspicions"):
            continue
        sts = by_case.get(cid)
        if sts is None:
            pred = 1  # unreviewed -> keep suspicion-based prediction
        elif mode == "any_supported":
            pred = 1 if "SUPPORTED" in sts else 0
        else:  # supported_or_unresolved
            pred = 1 if ("SUPPORTED" in sts or "UNRESOLVED" in sts) else 0
        g = labels[cid]
        tp += pred == 1 and g == 1
        fp += pred == 1 and g == 0
        fn += pred == 0 and g == 1
        tn += pred == 0 and g == 0
        if pred != g:
            mism.append((cid, pred, g))
    p = tp / (tp + fp) if tp + fp else 0
    r = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * p * r / (p + r) if p + r else 0
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "P": round(p, 4), "R": round(r, 4),
            "F1": round(f1, 4), "n": tp + fp + fn + tn, "mismatches": mism}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE.parent / "data" / "public46" / "public46.jsonl"))
    ap.add_argument("--labels", default=str(HERE.parent / "data" / "public46" / "labels_local.json"))
    ap.add_argument("--b23-dir", default=str(RESULTS / "B23_mistral_public46"))
    ap.add_argument("--reviewer", default=PROVIDER_ZAI, choices=[PROVIDER_ZAI, PROVIDER_MISTRAL])
    ap.add_argument("--out-name", default="B4x_glm_review_mistral_public46")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--max-seconds", type=float, default=480)
    ap.add_argument("--score-only", action="store_true")
    args = ap.parse_args()

    rows = {json.loads(l)["id"]: json.loads(l) for l in open(args.data, encoding="utf-8")}
    labels = json.loads(open(args.labels, encoding="utf-8").read())
    b23_dir = Path(args.b23_dir)
    out_dir = RESULTS / args.out_name
    if not args.score_only:
        run_batch_review(b23_dir, rows, args.reviewer, args.out_name, args.workers, args.max_seconds)
    for mode in ("any_supported", "supported_or_unresolved"):
        m = score_batch(b23_dir, out_dir, labels, mode)
        print(f"{args.out_name} [{mode}]:", json.dumps({k: v for k, v in m.items() if k != 'mismatches'}))
        (out_dir / f"metrics_{mode}.json").write_text(json.dumps(m, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

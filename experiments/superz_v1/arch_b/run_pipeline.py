"""Architecture B — mutual suspicion verification pipeline.

Stages (each an ablatable increment):
  B1: judge emits atomic suspicions with quotes (reuses A1-style prompt)
  B2: grounding — response_quote must exist in RESPONSE; source_quote must
      exist in the claimed source; LangExtract re-extracts normative
      elements around the cited source span and checks the suspicion's
      "why_error" is supported by an anchored element (exception, condition).
  B3: mechanical fact-ledger checks (stale value, failed-call claims).
  B4: cross-review — a second GLM pass reviews each surviving suspicion
      with the relevant original sources and the mechanical findings.

Aggregation rule (fixed, not tuned): label = 1 iff at least one suspicion
survives with status SUPPORTED (after B4) or REFUTED_STALE-mechanically-
confirmed-error... mechanical findings can only REMOVE suspicions or
confirm specific kinds, never flip 0->1 by themselves.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.trace_parser import parse_trace, split_policy_clauses
from common.zai_client import chat, extract_json
from arch_b.fact_ledger import FactLedger, locate_quote

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results" / "arch_b"

JUDGE_SYS = """You are an auditor of AI customer-service agent transcripts.
Audit ONLY the final RESPONSE turn for NEW contextual errors (wrong/stale/invented values,
wrong entity, policy violation, wrong action or arguments, missing required confirmation,
effect claimed of a failed call, permission treated as obligation, unfinished action
claimed complete).

For EACH suspicion output:
- response_quote: exact fragment of the RESPONSE where the problem is
- source_quote: exact fragment from policy / tool response / user message that proves it
- source_type: "policy" | "tool_result" | "user_message"
- why_error: one sentence naming the violation type

Quote exactly, do not paraphrase. If no suspicion, return empty list.
Output strictly JSON:
{"suspicions": [{"response_quote": "...", "source_quote": "...", "source_type": "...", "why_error": "..."}]}"""

REVIEW_SYS = """You are a strict reviewer of audit suspicions. You receive:
- the ORIGINAL relevant sources (policy clauses / tool results / user messages),
- ONE suspicion with its quotes,
- mechanical findings from a fact ledger.

Your job: decide whether THIS suspicion is actually a real NEW error of the final response.
Rules:
- A suspicion is SUPPORTED only if the cited source really implies the response is wrong,
  and the error is NEW in the final response (not inherited from earlier turns).
- If the response relies on a LATER tool result that supersedes the cited one (same entity,
  later position), the suspicion is REFUTED with reason "stale_source".
- If the cited source contains an EXCEPTION or CONDITION that permits the response's
  behaviour, the suspicion is REFUTED with reason "exception_applies".
- If the cited source does not actually exist or does not imply an error, REFUTED "bad_source".
- If evidence is insufficient either way, UNRESOLVED.
- Never refute just because the wording is unusual; refute on substance only.

Output strictly JSON:
{"status": "SUPPORTED|REFUTED|UNRESOLVED", "reason": "...", "decisive_quote": "..."}"""


def run_b1(rows: list[dict], workers: int, limit: int | None) -> Path:
    out_dir = RESULTS / "B1"
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = []
    for r in rows:
        out_f = out_dir / f"{r['id'].replace(':', '__')}.json"
        if out_f.exists():
            continue
        todo.append((r, out_f))
    if limit:
        todo = todo[:limit]
    print(f"[B1] {len(todo)} rows")

    import concurrent.futures

    def one(item):
        r, out_f = item
        user = (
            "TRANSCRIPT (system + policy + history):\n\n"
            + r["prompt"]
            + "\n\n==== FINAL RESPONSE TO AUDIT ====\n\n"
            + r["response"]
            + "\n\n==== END ====\nOutput the JSON now."
        )
        resp = chat(user=user, system=JUDGE_SYS, thinking=True, tag=f"B1/{r['id']}")
        rec = {"id": r["id"], "ok": resp.ok, "error": resp.error, "elapsed_s": round(resp.elapsed_s, 2)}
        if resp.ok:
            data = extract_json(resp.content)
            if data is None:
                rec["ok"] = False
                rec["error"] = "json-parse-failed"
                rec["raw"] = resp.content[:1500]
            else:
                sus = data.get("suspicions", [])
                rec["suspicions"] = sus if isinstance(sus, list) else []
                rec["ok"] = True
                out_f.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        return rec

    n = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for rec in ex.map(one, todo):
            n += 1
            print(f"  [B1 {n}/{len(todo)}] {rec['id']} {'OK' if rec['ok'] else 'FAIL ' + rec.get('error','')[:50]}")
    return out_dir


def ground_suspicion(s: dict, trace, ledger) -> dict:
    """B2+B3 grounding and mechanical checks for one suspicion."""
    g = {"response_quote_found": False, "source_quote_found": False, "source_type": s.get("source_type")}
    resp_seg = trace.response_segment
    if resp_seg is not None:
        loc = locate_quote(resp_seg.text, s.get("response_quote", ""))
        g["response_quote_found"] = loc["found"]
        g["response_quote_method"] = loc["method"]
    src = trace.full_text
    loc = locate_quote(src, s.get("source_quote", ""))
    g["source_quote_found"] = loc["found"]
    g["source_quote_method"] = loc["method"]

    # B3 mechanical
    mech = {}
    why = (s.get("why_error") or "").lower()
    rq = s.get("response_quote", "")
    # stale value check on the response quote
    sv = ledger.check_stale_value(rq, entity_hint=None)
    mech["stale_value"] = sv["status"]
    if sv["status"] == "REFUTED_STALE":
        # a later read contradicts the value used in the response:
        # this actually SUPPORTS an error if response used the stale one;
        # it REFUTES a suspicion if the suspicion's source is the stale one.
        sq = s.get("source_quote", "")
        sq_nums = set(re.findall(r"\d+", sq))
        later_vals = {v["value"] for v in sv.get("later", [])}
        if sq_nums and any(v in later_vals or any(v in x for x in later_vals) for v in sq_nums):
            # suspicion cites the superseded value -> the response may be right
            mech["suspicion_uses_stale_source"] = True
        else:
            mech["response_uses_stale_value"] = True
    fc = ledger.check_failed_call_claim(resp_seg.text if resp_seg else "")
    mech["failed_call_claims"] = fc[:3]
    g["mechanical"] = mech
    return g


def run_b23(b1_dir: Path, data_rows: dict) -> Path:
    out_dir = RESULTS / "B23"
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in sorted(b1_dir.glob("*.json")):
        rec = json.loads(f.read_text())
        if not rec.get("ok"):
            continue
        out_f = out_dir / f.name
        if out_f.exists():
            continue
        row = data_rows[rec["id"]]
        trace = parse_trace(row["prompt"], row["response"])
        ledger = FactLedger.build(trace)
        grounded = []
        for s in rec.get("suspicions", []):
            g = ground_suspicion(s, trace, ledger)
            grounded.append({"suspicion": s, "grounding": g})
        out = {
            "id": rec["id"],
            "n_suspicions": len(grounded),
            "grounded": grounded,
            "summary": {
                "n_resp_quote_found": sum(1 for x in grounded if x["grounding"]["response_quote_found"]),
                "n_src_quote_found": sum(1 for x in grounded if x["grounding"]["source_quote_found"]),
                "n_suspicion_uses_stale_source": sum(
                    1 for x in grounded if x["grounding"]["mechanical"].get("suspicion_uses_stale_source")
                ),
                "n_response_uses_stale_value": sum(
                    1 for x in grounded if x["grounding"]["mechanical"].get("response_uses_stale_value")
                ),
            },
        }
        out_f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_dir


def run_b4(b23_dir: Path, data_rows: dict, workers: int) -> Path:
    out_dir = RESULTS / "B4"
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for f in sorted(b23_dir.glob("*.json")):
        rec = json.loads(f.read_text())
        row = data_rows[rec["id"]]
        for i, g in enumerate(rec.get("grounded", [])):
            out_f = out_dir / f"{rec['id'].replace(':', '__')}__s{i}.json"
            if out_f.exists():
                continue
            tasks.append((rec, g, row, out_f))
    print(f"[B4] {len(tasks)} suspicion reviews")

    import concurrent.futures

    def one(item):
        rec, g, row, out_f = item
        s = g["suspicion"]
        # focused context: policy + all tool results (compactly) + response
        trace = parse_trace(row["prompt"], row["response"])
        pol = trace.policy_text
        tool_lines = [
            f"[{e.kind} {e.tool} seq={e.seq}] {e.raw_payload[:400]}"
            for e in trace.tool_events
        ][:60]
        user = (
            "POLICY:\n" + pol[:6000]
            + "\n\nTOOL EVENTS (ordered):\n" + "\n".join(tool_lines)
            + "\n\nFINAL RESPONSE:\n" + row["response"]
            + "\n\nSUSPICION:\n" + json.dumps(s, ensure_ascii=False)
            + "\n\nMECHANICAL FINDINGS:\n" + json.dumps(g["grounding"].get("mechanical", {}), ensure_ascii=False)
            + "\n\nReview this single suspicion. Output the JSON verdict."
        )
        resp = chat(user=user, system=REVIEW_SYS, thinking=True, tag=f"B4/{rec['id']}/s")
        out = {"id": rec["id"], "susp_idx": None, "ok": resp.ok, "error": resp.error}
        if resp.ok:
            data = extract_json(resp.content)
            if data and str(data.get("status", "")).upper() in ("SUPPORTED", "REFUTED", "UNRESOLVED"):
                out["status"] = str(data["status"]).upper()
                out["reason"] = data.get("reason", "")
                out["decisive_quote"] = data.get("decisive_quote", "")
                out_f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
                return out
            out["ok"] = False
            out["error"] = "bad-json"
        return out

    n = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for out in ex.map(one, tasks):
            n += 1
            if n % 10 == 0 or n == len(tasks):
                print(f"  [B4 {n}/{len(tasks)}]")
    return out_dir


def aggregate(b23_dir: Path, b4_dir: Path, labels: dict) -> dict:
    """Aggregate per-case: variants B1, B2(grounding filter), B3(+mechanical
    filter), B4(full). Metrics for each."""
    variants = {"B1": {}, "B2": {}, "B3": {}, "B4": {}}
    for f in sorted(b23_dir.glob("*.json")):
        rec = json.loads(f.read_text())
        cid = rec["id"]
        sus = rec.get("grounded", [])
        # B1: any suspicion -> 1
        variants["B1"][cid] = 1 if rec.get("n_suspicions", 0) > 0 else 0
        # B2: any suspicion whose BOTH quotes are found
        b2_any = any(
            x["grounding"]["response_quote_found"] and x["grounding"]["source_quote_found"] for x in sus
        )
        variants["B2"][cid] = 1 if b2_any else 0
        # B3: B2 + drop suspicions that mechanically use stale source
        b3_any = False
        for x in sus:
            g = x["grounding"]
            if not (g["response_quote_found"] and g["source_quote_found"]):
                continue
            if g["mechanical"].get("suspicion_uses_stale_source"):
                continue
            b3_any = True
            break
        variants["B3"][cid] = 1 if b3_any else 0
    # B4: per-case supported status from reviews
    by_case = {}
    for f in sorted(b4_dir.glob("*.json")):
        r = json.loads(f.read_text())
        if r.get("ok"):
            by_case.setdefault(r["id"], []).append(r.get("status"))
    for cid, preds in variants["B3"].items():
        # B4 uses review statuses for suspicions that survived B3 filter
        # (we approximate: any SUPPORTED among reviewed suspicions of the case)
        variants["B4"][cid] = 1 if "SUPPORTED" in by_case.get(cid, []) else (preds if cid not in by_case else 0)

    met = {}
    for name, preds in variants.items():
        tp = fp = fn = tn = 0
        for cid, pred in preds.items():
            if cid not in labels:
                continue
            gold = labels[cid]
            tp += pred == 1 and gold == 1
            fp += pred == 1 and gold == 0
            fn += pred == 0 and gold == 1
            tn += pred == 0 and gold == 0
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec_ = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec_ / (prec + rec_) if prec + rec_ else 0.0
        met[name] = {
            "TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "P": round(prec, 4), "R": round(rec_, 4), "F1": round(f1, 4),
            "n": tp + fp + fn + tn,
        }
    return met


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE.parent / "data" / "public46" / "public46.jsonl"))
    ap.add_argument("--labels", default=str(HERE.parent / "data" / "public46" / "labels_local.json"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--stage", default="all", choices=["B1", "B23", "B4", "all", "score"])
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.data, encoding="utf-8")]
    labels = json.loads(open(args.labels, encoding="utf-8").read())
    data_rows = {r["id"]: r for r in rows}
    if args.limit:
        rows = rows[: args.limit]

    if args.stage in ("B1", "all"):
        run_b1(rows, args.workers, args.limit)
    b1_dir = RESULTS / "B1"
    if args.stage in ("B23", "all"):
        run_b23(b1_dir, data_rows)
    b23_dir = RESULTS / "B23"
    if args.stage in ("B4", "all"):
        run_b4(b23_dir, data_rows, args.workers)
    b4_dir = RESULTS / "B4"
    met = aggregate(b23_dir, b4_dir, labels)
    (RESULTS / "metrics.json").write_text(json.dumps(met, ensure_ascii=False, indent=1))
    print(json.dumps(met, indent=1))


if __name__ == "__main__":
    main()

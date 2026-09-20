"""Architecture A — direct LLM judge baseline.

A0: direct binary label from (prompt, response).
A1: suspicion-first — model must enumerate concrete suspected errors with
    source quotes BEFORE giving a label (measures whether forced grounding
    of its own reasoning changes quality).

Uses z-ai GLM (glm-4-plus). Cached, resumable, parallel.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.zai_client import chat, extract_json
from common.trace_parser import parse_trace

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results" / "arch_a"

SYS_A0 = """You are an auditor of AI customer-service agent transcripts.
Input: a transcript with system instructions, a policy, a conversation history
(user messages, agent turns, tool calls and tool responses), and a final agent
turn (RESPONSE) that must be audited.

Task: decide whether the FINAL RESPONSE contains a contextual error:
- a factually wrong or unsupported statement about data seen in the transcript
  (wrong value, wrong entity, stale value, invented fact), OR
- a wrong action / tool call (violates policy, wrong arguments, missing
  required confirmation or precondition, forbidden action), OR
- a statement or action that contradicts the policy or the conversation.

The label is ONLY about NEW errors introduced in the final RESPONSE, not
about earlier turns. Uncertainty from earlier turns alone does not count.

Answer strictly as JSON: {"label": 0|1, "reason": "<short>"}"""

SYS_A1 = """You are an auditor of AI customer-service agent transcripts.
Input: a transcript with system instructions, a policy, a conversation history
(user messages, agent turns, tool calls and tool responses), and a final agent
turn (RESPONSE) that must be audited.

Task: audit ONLY the final RESPONSE for NEW contextual errors:
- factually wrong or unsupported statements about data seen in the transcript
  (wrong value, wrong entity, stale value, invented fact), OR
- wrong actions / tool calls (policy violation, wrong arguments, missing
  required confirmation or precondition, forbidden action), OR
- statements or actions contradicting the policy or conversation.

Procedure (mandatory):
1. For EACH suspected error, quote the exact fragment of the RESPONSE where
   it occurs, and quote the exact source fragment (from policy, tool result,
   or user message) that proves it is an error.
2. If you cannot find an exact proving source quote, the suspicion is
   unsupported - do not count it.
3. Only then give the label: 1 if at least one supported suspicion remains,
   else 0.

Answer strictly as JSON:
{"suspicions": [{"response_quote": "...", "source_quote": "...", "source_type": "policy|tool_result|user_message", "why_error": "..."}], "label": 0|1}"""


def build_user(prompt: str, response: str) -> str:
    return (
        "TRANSCRIPT (system + policy + history):\n\n"
        + prompt
        + "\n\n==== FINAL RESPONSE TO AUDIT ====\n\n"
        + response
        + "\n\n==== END ====\nNow output the JSON verdict."
    )


def run_variant(rows: list[dict], variant: str, workers: int, limit: int | None, max_seconds: float | None = None, provider: str = "zai", out_name: str | None = None) -> Path:
    out_dir = RESULTS / (out_name or variant)
    out_dir.mkdir(parents=True, exist_ok=True)
    sys_prompt = SYS_A0 if variant == "A0" else SYS_A1
    todo = []
    for r in rows:
        out_f = out_dir / f"{r['id'].replace(':', '__')}.json"
        if out_f.exists():
            continue
        todo.append((r, out_f))
    if limit:
        todo = todo[:limit]
    print(f"[{variant}] {len(todo)} rows to run (cache skipped)", flush=True)
    t_start = time.time()

    import concurrent.futures

    def one(item):
        r, out_f = item
        t0 = time.time()
        resp = chat(
            user=build_user(r["prompt"], r["response"]),
            system=sys_prompt,
            thinking=(variant != "A0"),  # A1 needs more careful reasoning
            tag=f"archA/{variant}/{r['id']}",
            provider=provider,
        )
        rec = {
            "id": r["id"],
            "variant": variant,
            "ok": resp.ok,
            "error": resp.error,
            "elapsed_s": round(time.time() - t0, 2),
            "model": resp.model,
        }
        if resp.ok:
            data = extract_json(resp.content)
            if data is None:
                rec["ok"] = False
                rec["error"] = "json-parse-failed"
                rec["raw"] = resp.content[:2000]
            else:
                if variant == "A0":
                    rec["label"] = int(data.get("label", -1)) if str(data.get("label", "-1")) in "01" else -1
                else:
                    sus = data.get("suspicions", [])
                    sus = sus if isinstance(sus, list) else []
                    rec["suspicions"] = sus
                    rec["label"] = int(data.get("label", -1)) if str(data.get("label", "-1")) in "01" else -1
            # persist only successful parses so failed calls retry on resume
            if rec["ok"] and rec.get("label") in (0, 1):
                out_f.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        return rec

    done = 0
    stop = False
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, item) for item in todo]
        for fut in concurrent.futures.as_completed(futs):
            rec = fut.result()
            done += 1
            status = "OK" if rec["ok"] else f"FAIL {rec.get('error','')[:60]}"
            print(f"  [{done}/{len(todo)}] {rec['id']} {status} ({rec['elapsed_s']}s)", flush=True)
            if max_seconds and time.time() - t_start > max_seconds:
                print(f"[{variant}] time budget reached, stopping gracefully", flush=True)
                for f2 in futs:
                    f2.cancel()
                stop = True
                break
    return out_dir


def score(out_dir: Path, labels: dict) -> dict:
    tp = fp = fn = tn = invalid = 0
    per_case = []
    for f in sorted(out_dir.glob("*.json")):
        rec = json.loads(f.read_text())
        if not rec.get("ok") or rec.get("label", -1) not in (0, 1):
            invalid += 1
            continue
        gold = labels[rec["id"]]
        pred = rec["label"]
        tp += pred == 1 and gold == 1
        fp += pred == 1 and gold == 0
        fn += pred == 0 and gold == 1
        tn += pred == 0 and gold == 0
        per_case.append({"id": rec["id"], "gold": gold, "pred": pred})
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec_ = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec_ / (prec + rec_) if prec + rec_ else 0.0
    m = {
        "n_scored": tp + fp + fn + tn,
        "invalid": invalid,
        "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "P": round(prec, 4), "R": round(rec_, 4), "F1": round(f1, 4),
        "per_case": per_case,
    }
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="A0", choices=["A0", "A1"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--data", default=str(HERE.parent / "data" / "public46" / "public46.jsonl"))
    ap.add_argument("--labels", default=str(HERE.parent / "data" / "public46" / "labels_local.json"))
    ap.add_argument("--score-only", action="store_true")
    ap.add_argument("--provider", default="zai", choices=["zai", "mistral"])
    ap.add_argument("--out-name", default=None)
    ap.add_argument("--max-seconds", type=float, default=480)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.data, encoding="utf-8")]
    labels = json.loads(open(args.labels, encoding="utf-8").read())
    variant_dir_name = args.out_name or args.variant
    out_dir = RESULTS / variant_dir_name

    if not args.score_only:
        out_dir = run_variant(rows, args.variant, args.workers, args.limit, args.max_seconds,
                              provider=args.provider, out_name=args.out_name)

    m = score(out_dir, labels)
    (RESULTS / f"{variant_dir_name}_metrics.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=1)
    )
    printable = {k: v for k, v in m.items() if k != "per_case"}
    print(json.dumps(printable, indent=1))


if __name__ == "__main__":
    main()

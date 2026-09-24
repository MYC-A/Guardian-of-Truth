#!/usr/bin/env python3
"""LettuceDetect v2 locator layer: local span-level locator + mechanical fragment verification.

Per user directive (2026-09-24): use LettuceDetect ONLY as a locator of candidate
unsupported fragments of the answer (relative to the policy text and tool results);
then verify each located fragment against observations and policy with code.
Its utility is measured by (a) missed errors found (none expected on public46 where
case-level recall is already 1.0), (b) NEW false positives introduced on the full
solution, and (c) whether the locator supplies the precise answer fragments that the
eight mechanical/TQ operations need (fragment-supply diagnostic).

Models (local, MIT): KRLabsOrg/lettucedect-v2-mmbert-base (encoder) with
lettucedect-v2-taxonomy-head; optional KRLabsOrg/lettucedect-v2-qwen-2b (generative,
typed spans + short reason) for the same cases as a second locator pass.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HOME", "/mnt/data/guardian/agent-workspace/hf_cache")
os.environ.setdefault("HF_HUB_CACHE", "/mnt/data/guardian/agent-workspace/hf_cache/hub")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

DEFAULT_RECORDS = REPO / "outputs/big_researh/p_api/pgjudge/records.jsonl"
DEFAULT_CASES = REPO / "outputs/full21/input/public46_label_free.csv"
DEFAULT_GOLD = REPO / "outputs/searh_23/baseline_frozen/control_repro_percase.csv"
DEFAULT_V31 = REPO / "outputs/searh_23/fp_diagnostic/refute_layer_v3_v31.json"
DEFAULT_TQ = REPO / "outputs/searh_23/tq_layer/tq_questions.json"

csv.field_size_limit(2 ** 30)

ID_RE = re.compile(r"\b(?:[A-Z]{2,}\d{4,}|W\d{7}|\d{8,10}|HAT\d{3})\b")
NUM_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
STATUS_WORDS = {
    "active": {"активн", "active", "разморожен", "unfrozen", "confirmed", "подтвержд"},
    "frozen": {"заморожен", "frozen"},
    "failed": {"не прош", "failed", "declined", "отклон", "error", "ошибк"},
    "success": {"успешн", "successful", "успешно"},
    "pending": {"pending", "в обработке", "ожидает"},
    "cancelled": {"отмен", "cancelled", "canceled"},
}
ACTION_HINTS = [r"заброн|бронирован|booking|booked", r"отмен[еи]|cancell", r"возврат|refund",
                r"разморож|unfreez", r"перевод|transfer", r"оформ|process", r"верифиц|verif",
                r"проверил|checked|validated"]
RESP_LINE = re.compile(r"← TOOL_RESPONSE ([\w.-]+): (.*)")
CALL_LINE = re.compile(r"→ TOOL_CALL ([\w.-]+)")
POLICY_RE = re.compile(r"<policy>(.*?)</policy>", re.DOTALL | re.IGNORECASE)


def policy_text(case: dict) -> str:
    m = POLICY_RE.search(case["prompt"])
    return m.group(1) if m else case["prompt"]


def observations(prompt: str) -> list[dict]:
    return [{"tool": m.group(1), "text": m.group(2)} for m in RESP_LINE.finditer(prompt)]


def latest_obs_for(ids: set[str], obs: list[dict]) -> dict[str, dict]:
    latest = {}
    for o in obs:
        for i in ids:
            if i in o["text"]:
                latest[i] = o
    return latest


def verify_span(span: dict, fr: dict) -> dict:
    """Mechanical verification of one located fragment against observations + policy + user turns.

    Grounding rules (logic-level):
    - entity ids must appear in TOOL OBSERVATIONS (the user's own words do not ground an id);
    - numeric values ground in observations, policy, OR user turns (the agent may restate
      what the user said) — but never in its own earlier text;
    - tool-call line spans ground iff the called tool is declared in the policy catalog;
    - trivial fragments (<2 word chars, or a bare number <3 digits) are noise and skipped.
    """
    text = span["text"] or ""
    stripped = text.strip()
    word_chars = sum(ch.isalnum() for ch in stripped)
    if word_chars < 2:
        return {"verdict": "NOISE", "why": "trivial fragment", "ids": [], "ids_missing": [], "nums_missing": []}
    if not any(ch.isalpha() for ch in stripped):
        digits = re.sub(r"\D", "", stripped)
        if len(digits) < 3:
            return {"verdict": "NOISE", "why": "bare short number", "ids": [], "ids_missing": [], "nums_missing": []}
    if stripped.startswith("→ TOOL_CALL"):
        m = re.match(r"→ TOOL_CALL ([\w.-]+)", stripped)
        tool = m.group(1) if m else ""
        declared = tool in fr["policy"] or tool in fr["all_call_names"]
        return {"verdict": "GROUNDED" if declared else "UNDECLARED_TOOL",
                "why": (f"tool {tool} declared in policy/catalog" if declared
                        else f"tool {tool} not declared"),
                "ids": [], "ids_missing": [], "nums_missing": []}
    obs_blob = " ".join(o["text"] for o in fr["obs"])
    pol = fr["policy"]
    user_blob = fr["user_blob"]
    ids = set(ID_RE.findall(text))
    ids_in_obs = {i for i in ids if any(i in o["text"] for o in fr["obs"])}
    ids_missing = ids - ids_in_obs
    # status claims vs latest observation for the observed entities
    span_status = {k for k, ws in STATUS_WORDS.items() if any(w in text.lower() for w in ws)}
    status_conflict, status_match = None, None
    if ids_in_obs:
        latest = latest_obs_for(ids_in_obs, fr["obs"])
        latest_blob = " ".join(v["text"] for v in latest.values())
        obs_status = {k for k, ws in STATUS_WORDS.items() if any(w in latest_blob.lower() for w in ws)}
        if span_status and obs_status:
            if span_status & obs_status:
                status_match = sorted(span_status & obs_status)
            else:
                status_conflict = (sorted(span_status), sorted(obs_status))
    # numbers grounding (observations, policy, or the user's own words)
    nums = [n for n in NUM_RE.findall(text) if len(n.replace(".", "").replace(",", "")) >= 2]
    nums_missing = [n for n in nums if n not in obs_blob and n not in pol and n not in user_blob]

    if ids_missing and not ids_in_obs:
        verdict = "UNSUPPORTED_ID"
        why = f"entity ids {sorted(ids_missing)} not present in any observation"
    elif status_conflict:
        verdict = "CONTRADICTED_STATUS"
        why = f"claim status {status_conflict[0]} vs latest observation status {status_conflict[1]}"
    elif nums_missing and not ids_in_obs and not status_match:
        verdict = "UNSUPPORTED_VALUE"
        why = f"numeric values {nums_missing[:5]} not found in observations, policy or user turns"
    elif status_match and not status_conflict:
        verdict = "GROUNDED"
        why = f"status {status_match} matches latest observation"
    elif ids_in_obs and not status_conflict:
        verdict = "GROUNDED"
        why = "referenced entities observed"
    else:
        verdict = "UNDECIDABLE"
        why = "no mechanical anchor"
    return {"verdict": verdict, "why": why,
            "ids": sorted(ids), "ids_missing": sorted(ids_missing),
            "nums_missing": nums_missing[:6]}


def run_encoder(cases: dict, out: dict) -> None:
    from lettucedetect.models.inference import HallucinationDetector
    detector = HallucinationDetector(
        method="transformer",
        model_path="KRLabsOrg/lettucedect-v2-mmbert-base",
        taxonomy_head="KRLabsOrg/lettucedect-v2-taxonomy-head")
    for n, (cid, case) in enumerate(sorted(cases.items())):
        fr = {"obs": observations(case["prompt"]), "policy": policy_text(case),
              "all_call_names": re.findall(r"→ TOOL_CALL ([\w.-]+)", case["prompt"])
              + re.findall(r"→ TOOL_CALL ([\w.-]+)", case["response"]),
              "user_blob": " ".join(re.findall(r"⟦USER⟧\n(.*?)(?=⟦|\Z)", case["prompt"], re.DOTALL))}
        question = (case["prompt"].split("⟦USER⟧")[-1] or "")[:1500]
        try:
            preds = detector.predict(context=[fr["policy"], " ".join(o["text"] for o in fr["obs"])],
                                     question=question, answer=case["response"],
                                     output_format="spans")
        except Exception as exc:
            out[cid] = {"error": f"encoder predict failed: {exc}"}
            continue
        verified = []
        for s in preds or []:
            v = verify_span(s, fr)
            v.update({"start": s.get("start"), "end": s.get("end"), "text": s.get("text"),
                      "category": s.get("category"), "subcategory": s.get("subcategory"),
                      "confidence": round(float(s.get("confidence", 0)), 4)})
            verified.append(v)
        out[cid] = {"fr_obs_count": len(fr["obs"]), "spans": verified}
        print(f"[encoder {n + 1}/{len(cases)}] {cid[:56]} spans={len(verified)} "
              f"verdicts={[v['verdict'] for v in verified][:6]}", flush=True)


def run_generative(cases: dict, out: dict) -> None:
    from lettucedetect.models.inference import HallucinationDetector
    detector = HallucinationDetector(method="transformer",
                                     model_path="KRLabsOrg/lettucedect-v2-qwen-2b")
    for n, (cid, case) in enumerate(sorted(cases.items())):
        if cid not in out or "spans" not in out.get(cid, {}):
            out.setdefault(cid, {})
        fr = {"obs": observations(case["prompt"]), "policy": policy_text(case),
              "all_call_names": re.findall(r"→ TOOL_CALL ([\w.-]+)", case["prompt"])
              + re.findall(r"→ TOOL_CALL ([\w.-]+)", case["response"]),
              "user_blob": " ".join(re.findall(r"⟦USER⟧\n(.*?)(?=⟦|\Z)", case["prompt"], re.DOTALL))}
        question = (case["prompt"].split("⟦USER⟧")[-1] or "")[:1500]
        try:
            preds = detector.predict(context=[fr["policy"], " ".join(o["text"] for o in fr["obs"])],
                                     question=question, answer=case["response"],
                                     output_format="spans")
        except Exception as exc:
            out[cid]["generative_error"] = str(exc)[:300]
            continue
        verified = []
        for s in preds or []:
            v = verify_span(s, fr)
            v.update({"start": s.get("start"), "end": s.get("end"), "text": s.get("text"),
                      "category": s.get("category"), "subcategory": s.get("subcategory"),
                      "confidence": round(float(s.get("confidence", 0)), 4) if s.get("confidence") else None})
            verified.append(v)
        out[cid]["generative_spans"] = verified
        print(f"[gen-2b {n + 1}/{len(cases)}] {cid[:56]} spans={len(verified)}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    ap.add_argument("--gold-json", default="",
                    help="json {id: label} (e.g. hotel expected.json); overrides --gold")
    ap.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    ap.add_argument("--v31", type=Path, default=DEFAULT_V31)
    ap.add_argument("--tq", type=Path, default=DEFAULT_TQ)
    ap.add_argument("--out", type=Path, default=REPO / "outputs/searh_23/ld_layer")
    ap.add_argument("--tag", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pass", dest="passes", default="encoder", choices=["encoder", "generative", "both"])
    args = ap.parse_args()

    cases = {r["id"]: r for r in csv.DictReader(open(args.cases, encoding="utf-8"))}
    if args.limit:
        cases = dict(list(sorted(cases.items()))[: args.limit])
    if args.gold_json:
        gold = {k: int(v) for k, v in json.load(open(args.gold_json, encoding="utf-8")).items()}
    else:
        gold = {r["id"]: int(r["gold"]) for r in csv.DictReader(open(args.gold, encoding="utf-8"))}
    v31_labels = {e["id"]: e["new_label"] for e in json.loads(args.v31.read_text(encoding="utf-8")).get("per_case", [])}
    tq_labels = {}
    if args.tq.is_file():
        tq_labels = {e["id"]: e["new_label"] for e in json.loads(args.tq.read_text(encoding="utf-8")).get("per_case", [])}
    # decision of the v3.1+TQ stack (arms base): pgjudge -> v3.1 -> TQ
    base = {}
    recs = {json.loads(l)["id"]: json.loads(l)["label"] for l in open(args.records, encoding="utf-8")}
    for cid in cases:
        base[cid] = 0
        if recs.get(cid) == 1:
            if v31_labels.get(cid, 1) == 1:
                base[cid] = 1 if tq_labels.get(cid, 1) == 1 else 0

    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / f"ld_locator{args.tag}.json"
    out = {}
    if out_path.exists():
        wrapped = json.loads(out_path.read_text(encoding="utf-8"))
        out = wrapped.get("spans_by_case", wrapped)
    t0 = time.time()
    if args.passes in ("encoder", "both"):
        run_encoder(cases, out)
    if args.passes in ("generative", "both"):
        run_generative(cases, out)

    # ---- analysis: LD as candidate flagger over the FULL solution ----
    def case_signal(entry: dict, key: str = "spans") -> bool:
        """LD proposes a violation only via code-confirmed unsupported/contradicted fragments."""
        for s in entry.get(key, []) or []:
            if s.get("verdict") in ("UNSUPPORTED_ID", "UNSUPPORTED_VALUE", "CONTRADICTED_STATUS", "UNDECLARED_TOOL"):
                return True
        return False

    rows, new_fp, missed_found, frag_stats = [], [], [], {"alarms": 0, "supplied": 0}
    tq_claims_by_case = {}
    if args.tq.is_file():
        tq = json.loads(args.tq.read_text(encoding="utf-8"))
        for e in tq.get("per_case", []):
            claims = []
            for cr in e.get("cards", []):
                for cl in (cr.get("fragments", {}).get("claims") or []):
                    claims.append(cl["text"])
            tq_claims_by_case[e["id"]] = claims
    for cid in sorted(cases):
        entry = out.get(cid, {})
        spans = entry.get("spans", []) or []
        g = gold.get(cid)
        b = base.get(cid, 0)
        sig = case_signal(entry)
        ld_label = 1 if (b == 1 or sig) else 0
        row = {"id": cid, "gold": g, "base": b, "ld_new_flag": sig, "ld_label": ld_label,
               "n_spans": len(spans),
               "n_unsup": sum(1 for s in spans if s.get("verdict", "").startswith("UNSUPPORTED")),
               "n_contrad": sum(1 for s in spans if s.get("verdict") == "CONTRADICTED_STATUS"),
               "cats": sorted({s.get("category") for s in spans if s.get("category")})}
        if sig and b == 0 and g == 0:
            new_fp.append(cid)
        if sig and b == 0 and g == 1:
            missed_found.append(cid)
        # fragment-supply: does an LD span overlap a TQ claim fragment on alarm cases?
        if b == 1 and tq_claims_by_case.get(cid):
            frag_stats["alarms"] += 1
            supplied = False
            for s in spans:
                st = s.get("text", "").lower()
                for cl in tq_claims_by_case[cid]:
                    toks = [w for w in re.split(r"\W+", cl.lower()) if len(w) > 4]
                    if toks and sum(1 for w in toks if w in st) / len(toks) >= 0.4:
                        supplied = True
                        break
                if supplied:
                    break
            if supplied:
                frag_stats["supplied"] += 1
        rows.append(row)

    tp = sum(1 for r in rows if r["ld_label"] == 1 and r["gold"] == 1)
    fp = sum(1 for r in rows if r["ld_label"] == 1 and r["gold"] == 0)
    fn = sum(1 for r in rows if r["ld_label"] == 0 and r["gold"] == 1)
    res = {"layer": "LettuceDetect v2 locator (encoder+taxonomy) + mechanical verification",
           "models": ["KRLabsOrg/lettucedect-v2-mmbert-base", "KRLabsOrg/lettucedect-v2-taxonomy-head"],
           "passes_run": args.passes, "elapsed_s": round(time.time() - t0, 1),
           "base_after": {"TP": sum(1 for r in rows if r["base"] == 1 and r["gold"] == 1),
                          "FP": sum(1 for r in rows if r["base"] == 1 and r["gold"] == 0)},
           "ld_arm": {"TP": tp, "FP": fp, "FN": fn,
                      "F1": round(2 * tp / (2 * tp + fp + fn), 4) if tp else 0.0},
           "new_fp_introduced": new_fp, "missed_errors_found": missed_found,
           "fragment_supply": frag_stats,
           "per_case": rows}
    out_path.write_text(json.dumps({"results": res, "spans_by_case": out}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

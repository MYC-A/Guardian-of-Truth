#!/usr/bin/env python3
"""BIG_RESEARH S6-targeted prototype: per-suspicion extraction (directive: <=30min runs).

Instead of full-history extraction (48k chars -> 200-320 extractions, ~31-43%
span-valid, 7-14 min/case), extract ONLY facts relevant to ONE specific
suspicion/obligation with bounded context (policy + history tail + response,
~12k chars) and a strict 5-class contract.

Measured per case:
  n_extractions, n_span_ok, n_new_vs_graph, latency, class purity,
  suspicion relevance (content-word Jaccard), downstream mapping
  (P-card overlap / B2 confirmation / B1 tool evidence / S8 premise fill).

Backend: existing local mistral-7b server (declared substitute channel;
Mistral API unavailability is documented in outputs/big_researh/s6_diagnostic/api_check.json).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments" / "full21"))
sys.path.insert(0, str(REPO / "experiments" / "superz_fullcycle"))
sys.path.insert(0, str(REPO / "src"))

import langextract as lx  # noqa: E402
from langextract.providers.openai import OpenAILanguageModel  # noqa: E402

from g_graph import graph_digest  # noqa: E402
from run_granite_modes import read_cases  # noqa: E402
from s6_langextract import EXAMPLE, span_ok, new_fact  # noqa: E402

BASE_URL = "http://127.0.0.1:8002/v1"
MODEL_ID = "mistral-7b-instruct-v0.3"

ARCH = REPO.parent / "Guardian-superz-fullcycle"
E3B = ARCH / "outputs" / "superz_fullcycle" / "e3b_a1r_live" / "blockrun" / "records.jsonl"
CARDS = ARCH / "outputs" / "superz_fullcycle" / "p_precond" / "extract_blockrun" / "cards.jsonl"
DIAG_SET = REPO / "outputs" / "big_researh" / "s6_diagnostic" / "diagnostic_set.json"

OUT_DIR = REPO / "outputs" / "big_researh" / "s6_targeted"
ALLOWED_CLASSES = {"policy_obligation", "policy_exception", "temporal_constraint",
                   "user_commitment", "tool_confirmation"}
CONFIRM_TOKENS = ("yes", "confirm", "confirmed", "да", "подтверждаю", "согласен",
                  "конечно", "подтверждение")

TARGETED_HINT = (
    "You verify ONE proposed error suspicion about a customer-service agent's final "
    "response. From the provided POLICY, RECENT HISTORY and RESPONSE extract only the "
    "facts that support or refute THIS suspicion: the applicable policy requirement with "
    "its conditions, exceptions and temporal limits, the user's relevant statements or "
    "confirmations, and the tool results that bear on the suspicion. Use ONLY these "
    "extraction classes: policy_obligation, policy_exception, temporal_constraint, "
    "user_commitment, tool_confirmation. Extract only text present verbatim in the source."
)


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip().lower()


def content_words(t: str) -> set:
    return {w for w in re.findall(r"[a-zа-яё0-9_-]{4,}", norm(t))}


def overlap_words(a: str, b: str) -> float:
    wa, wb = content_words(a), content_words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def policy_region(prompt: str) -> str:
    m = re.search(r"<policy>(.*?)</policy>", prompt, re.DOTALL)
    return m.group(1) if m else prompt[:6000]


def build_source(case: dict, hist_tail: int = 7000, resp_max: int = 4000) -> str:
    prompt = case["prompt"]
    pol = policy_region(prompt)[:8000]
    tail = prompt[-hist_tail:] if len(prompt) > hist_tail else prompt
    resp = case["response"][:resp_max]
    return ("POLICY:\n" + pol + "\n\nRECENT HISTORY (tail):\n" + tail +
            "\n\nRESPONSE:\n" + resp)


def pick_obligation(cid: str) -> dict:
    """E3b suspicion (prefer producer-flagged, top score) -> else P card."""
    if E3B.exists():
        for line in open(E3B, encoding="utf-8"):
            r = json.loads(line)
            if r.get("id") != cid or r.get("status") != "OK":
                continue
            susp = [s for s in r.get("suspicions", [])
                    if (s.get("proposed_violation") or "").strip()]
            if susp:
                flagged = [s for s in susp if s.get("label") == 1]
                pool = flagged or susp
                best = max(pool, key=lambda s: s.get("score") or 0)
                return {"kind": "e3b_suspicion", "producer_label": best.get("label"),
                        "score": best.get("score"), "reason_type": best.get("reason_type"),
                        "text": best["proposed_violation"]}
    if CARDS.exists():
        for line in open(CARDS, encoding="utf-8"):
            r = json.loads(line)
            if r.get("id") == cid and r.get("status") == "OK" and r.get("cards"):
                c = r["cards"][0]
                return {"kind": "p_card", "producer_label": None, "score": None,
                        "reason_type": c.get("obligation_kind"),
                        "text": (c.get("obligation_summary") or "") + " | required: " +
                                (c.get("required_state_or_action") or "")}
    return {"kind": "none", "producer_label": None, "score": None,
            "reason_type": None, "text": ""}


def p_cards_for(cid: str) -> list:
    out = []
    if CARDS.exists():
        for line in open(CARDS, encoding="utf-8"):
            r = json.loads(line)
            if r.get("id") == cid and r.get("status") == "OK":
                out = [c for c in r.get("cards", []) if c.get("quote_grounded")]
    return out


def s8_binding_for(cid: str) -> list:
    p = REPO / "outputs" / "big_researh" / "s8_clingo" / "cards_verified.jsonl"
    out = []
    if p.exists():
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            if r.get("id") == cid:
                out.append({"binding": r.get("binding"),
                            "premises": r.get("premises"),
                            "verdict": r.get("verdict")})
    return out


def map_downstream(extr: dict, susp_text: str, pcards: list) -> list:
    tags = []
    cls = extr.get("class")
    txt = norm(extr.get("text"))
    if cls in ("policy_obligation", "policy_exception", "temporal_constraint"):
        tags.append("P/S8-policy-side")
        for c in pcards:
            q = norm(c.get("policy_quote", ""))
            if q and (q in txt or txt in q or overlap_words(q, txt) >= 0.4):
                tags.append("P-card-overlap")
                break
    if cls == "policy_exception":
        tags.append("S8-exception-fill")
    if cls == "user_commitment" and any(tok in txt for tok in CONFIRM_TOKENS):
        tags.append("B2-confirmation-evidence")
    if cls == "tool_confirmation":
        tags.append("B1/tool-evidence")
    if susp_text and overlap_words(susp_text, extr.get("text") or "") >= 0.2:
        tags.append("suspicion-relevant")
    return tags


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=7)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rec_path = OUT_DIR / "records.jsonl"
    diag = json.loads(DIAG_SET.read_text())["diagnostic_set"][:args.limit]

    gold, granite = {}, {}
    for row in csv.DictReader(open(REPO / "outputs/full21/control_repro_percase.csv")):
        gold[row["id"]] = int(row["gold"])
        granite[row["id"]] = int(row["granite_repro"])

    done = set()
    if rec_path.exists():
        for line in open(rec_path, encoding="utf-8"):
            try:
                done.add(json.loads(line)["id"])
            except Exception:
                pass

    model = OpenAILanguageModel(model_id=MODEL_ID, api_key="local-no-key",
                                base_url=BASE_URL, temperature=0.0, max_workers=1)
    cases = {c["id"]: c for c in read_cases(
        REPO / "outputs/full21/input/public46_label_free.csv")}

    for cid in diag:
        if cid in done:
            continue
        t0 = time.perf_counter()
        case = cases[cid]
        source = build_source(case)
        obl = pick_obligation(cid)
        pcards = p_cards_for(cid)
        s8 = s8_binding_for(cid)
        rec = {"id": cid, "gold": gold.get(cid), "granite": granite.get(cid),
               "obligation": obl, "n_p_cards": len(pcards), "s8_bindings": s8,
               "source_chars": len(source)}
        try:
            result = lx.extract(
                source,
                prompt_description=TARGETED_HINT + (
                    "\nSUSPICION TO VERIFY: " + (obl["text"] or "(none)")[:800]),
                examples=[EXAMPLE],
                model=model,
                show_progress=False,
            )
            if isinstance(result, list):
                docs = [d for d in result if d is not None]
                result = docs[0] if docs else None
            raw = list(getattr(result, "extractions", []) or []) if result else []
            extractions = []
            for ex in raw:
                cls = getattr(ex, "extraction_class", None)
                txt = getattr(ex, "extraction_text", None)
                iv = getattr(ex, "char_interval", None)
                s = getattr(iv, "start_pos", None) if iv else None
                e = getattr(iv, "end_pos", None) if iv else None
                ok = span_ok(txt, s, e, source) if txt else False
                extractions.append({
                    "class": cls, "text": txt, "start": s, "end": e, "span_ok": ok,
                    "class_in_contract": cls in ALLOWED_CLASSES})
            try:
                digest = graph_digest(case["prompt"], case["response"])
            except Exception:
                digest = ""
            for x in extractions:
                x["is_new_vs_graph"] = bool(
                    x["span_ok"] and new_fact(x["text"] or "", digest))
                x["downstream"] = map_downstream(x, obl.get("text") or "", pcards)
            rec.update({
                "n_extractions": len(extractions),
                "n_span_ok": sum(1 for x in extractions if x["span_ok"]),
                "n_class_in_contract": sum(1 for x in extractions
                                           if x["class_in_contract"]),
                "n_new_vs_graph": sum(1 for x in extractions if x["is_new_vs_graph"]),
                "n_suspicion_relevant": sum(1 for x in extractions
                                            if "suspicion-relevant" in x["downstream"]),
                "downstream_tag_counts": dict(
                    __import__("collections").Counter(
                        t for x in extractions for t in x["downstream"])),
                "latency_s": round(time.perf_counter() - t0, 1),
                "extractions": extractions,
            })
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
            rec["latency_s"] = round(time.perf_counter() - t0, 1)
        with open(rec_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
        print(f"[s6t] {cid}: extr={rec.get('n_extractions', 'ERR')} "
              f"span_ok={rec.get('n_span_ok', 0)} "
              f"contract={rec.get('n_class_in_contract', 0)}/"
              f"{rec.get('n_extractions', 0)} "
              f"new={rec.get('n_new_vs_graph', 0)} "
              f"rel={rec.get('n_suspicion_relevant', 0)} "
              f"({rec.get('latency_s', '?')}s)", flush=True)

    # summary
    rows = [json.loads(l) for l in open(rec_path, encoding="utf-8")]
    ok_rows = [r for r in rows if "error" not in r]
    summary = {
        "cases_attempted": len(rows), "cases_ok": len(ok_rows),
        "errors": len(rows) - len(ok_rows),
        "mean_extractions": round(sum(r["n_extractions"] for r in ok_rows) / max(1, len(ok_rows)), 1),
        "mean_span_ok": round(sum(r["n_span_ok"] for r in ok_rows) / max(1, len(ok_rows)), 1),
        "mean_latency_s": round(sum(r["latency_s"] for r in ok_rows) / max(1, len(ok_rows)), 1),
        "full_history_reference": {
            "mean_extractions": 260.75, "mean_span_ok": 92.5, "mean_latency_s": 648.8,
            "note": "4 full-history cases (311/319/202/211 extr; 99/99/87/85 span_ok; 824/845/490/436 s)"},
        "verdict_rule": (
            "adds_missing_evidence := exists(span_ok & new_vs_graph & "
            "(suspicion-relevant | downstream-tag)) — counted per case below"),
        "per_case": [
            {"id": r["id"], "gold": r.get("gold"), "granite": r.get("granite"),
             "adds_missing_evidence": bool(
                 any(x.get("is_new_vs_graph") and
                     ("suspicion-relevant" in x.get("downstream", []) or
                      x.get("downstream"))
                     for x in r.get("extractions", [])))}
            for r in ok_rows],
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

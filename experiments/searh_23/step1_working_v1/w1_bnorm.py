"""W1-H1b: LLM boundary normalizer v2 (extractive-subspan discipline).

For every grounded candidate span: ask the LLM to decide boundary status
(KEEP / NORMALIZE / SPLIT) AND to anchor the predicate of each resulting
span. Returned spans MUST be exact substrings of the original candidate
span - verified deterministically; violations fall back to KEEP.

The predicate anchor is the deterministic input for the node certificate
(directive §7 Q1 "where is the predicate?"): it must be an exact substring
of its span, otherwise the candidate is marked predicate_unanchored.

v2 lessons (F2 dev run): the normalizer must never drop imperative
clauses, copula/passive state clauses or action nominalizations; drops
belong to the type filter (EVENTLIKE) and the node certificate, not here.
Only predicate-less object NPs may be dropped.

Writes outputs/W1_BNORM/<ARM>/<case>.json.

Run: python3 w1_bnorm.py LLM_SG|CUR|W1_HYG   (LF_SUITE=main|f2)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
PL = HERE.parent / "policy_licensing_v1"
sys.path[:0] = [str(PL)]
from pl_common import Mistral  # noqa: E402

OUT = HERE / "outputs"

BNORM_SYSTEM = """You normalize candidate event mentions extracted from a workplace policy. You see ONE candidate span (an exact substring of the policy). Decide its boundary status. Every span you output MUST be an exact substring of the candidate span, copied character by character. Never paraphrase, never add words.

A well-formed mention is either:
- a verbal clause: the action predicate plus its required argument phrases (INCLUDING complements like "of turbine 12", "for mold", "reel 7"): "Inspect the blades of turbine 12";
- a state clause with copula or passive: "the tower is drained", "the interior is clean";
- an action nominalization phrase (a reference to an action): "the cleaning", "Storage of the master", "scraping", "the inspection";
- an imperative clause: "Drain tower 4", "Feed the otters".

These forms are KEEP as-is (their boundary is already correct).

A span needs NORMALIZE when it contains extra material beyond one mention:
- time or place adjuncts: "Incubate the plate at thirty degrees" -> "Incubate the plate"; "Groom slope 2 before dawn" -> "Groom slope 2";
- trailing subordinate clauses after connectives (only after, after, before, when, only if, unless, until): "Clean the interior only after the tower is drained" -> "Clean the interior"; "Transmit only if the swr reading is below two" -> "Transmit";
- destination or instrument phrases of the containing sentence: "Record the annealing in the batch log" -> "Record the annealing".

A span needs SPLIT when it conjoins two or more separate clauses or mentions: "the inspection is logged and the mold check is negative" -> two spans "the inspection is logged" and "the mold check is negative".

DROP only when the span contains NO predicate of any kind (no verb, no copula, no passive, no action nominalization): a pure object, participant, time or value phrase like "reel 7", "the batch log", "thirty degrees".

For each output span also give its predicate: the exact substring that is the action/state verb, the copula+participle, or the nominalization head (e.g. for "the cleaning" the predicate is "cleaning"; for "the tower is drained" it is "is drained"; for "Transmit" it is "Transmit"). For a DROP, spans is empty.

Answer strictly as JSON:
{"decision": "KEEP|NORMALIZE|SPLIT|DROP",
 "spans": [{"span": "<exact substring>", "predicate": "<exact substring of the span or null>"}],
 "reason": "<short>"}"""


def load_suite() -> list[dict]:
    fname = ("level_f2_cases.json" if os.environ.get("LF_SUITE") == "f2"
             else "level_f_cases.json")
    return json.loads((IE / "frozen" / fname).read_text(encoding="utf-8"))


def load_candidates(arm: str, case_id: str) -> list[dict]:
    for base in (OUT / "W1_HYG", IE / "outputs"):
        f = base / arm / f"{case_id}.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))["candidates"]
    return []


def _ask(client, system: str, user: str, mt: int = 400) -> dict:
    for _ in range(4):
        try:
            r = client.ask(system, user, max_tokens=mt)
            parsed, _err = Mistral.parse_json(r["raw"])
            if parsed:
                return parsed
        except Exception:
            time.sleep(3)
    return {}


def normalize_span(client, span: str, ctx: str) -> tuple[str, list[dict]]:
    """Returns (decision, [{span, predicate}]). Every span is verified to
    be an exact substring of the original (case-tolerant)."""
    user = (f"CANDIDATE SPAN:\n\"{span}\"\n\n"
            f"SENTENCE CONTEXT (for reference only):\n\"{ctx}\"\n\n"
            "Decide the boundary status and anchor the predicate. Answer "
            "strictly as JSON.")
    ans = _ask(client, BNORM_SYSTEM, user)
    dec = (ans.get("decision") or "KEEP").upper()
    raw = ans.get("spans") or []
    if isinstance(raw, list) and raw and isinstance(raw[0], str):
        raw = [{"span": s, "predicate": None} for s in raw if
               isinstance(s, str)]
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        s = item.get("span")
        p = item.get("predicate")
        if not isinstance(s, str) or not s.strip():
            continue
        s = s.strip().strip('"').strip()
        if not (s and (s in span or s.lower() in span.lower())):
            continue
        pred_ok = isinstance(p, str) and p.strip() and \
            (p.strip() in s or p.strip().lower() in s.lower())
        out.append({"span": s,
                    "predicate": p.strip() if pred_ok else None})
    if dec in ("NORMALIZE", "SPLIT") and not out:
        dec = "KEEP"
    if dec == "KEEP":
        out = [{"span": span, "predicate": None}]
    if dec == "DROP":
        out = []
    return dec, out[:4]


def main() -> None:
    arm = sys.argv[1] if len(sys.argv) > 1 else "LLM_SG"
    client = Mistral(model="ministral-14b-latest", cache_dir=OUT / "_cache")
    dst = OUT / "W1_BNORM" / arm
    dst.mkdir(parents=True, exist_ok=True)
    stats = Counter()
    # fresh dir when prompt changed
    import hashlib
    tag = hashlib.sha256(BNORM_SYSTEM.encode()).hexdigest()[:8]
    dst = OUT / f"W1_BNORM_{tag}" / arm
    dst.mkdir(parents=True, exist_ok=True)

    def sent_of(start, policy):
        pos = 0
        for s in re.split(r"(?<=[.!?])\s+", policy):
            if pos <= start < pos + len(s):
                return s.strip()
            pos += len(s) + 1
        return ""

    for case in load_suite():
        path = dst / f"{case['case_id']}.json"
        if path.exists():
            continue
        policy = case["policy"]
        cands = load_candidates(arm, case["case_id"])
        out_cands = []
        for c in cands:
            span = c.get("span") or ""
            if not span or c.get("start") is None:
                continue  # ungrounded dropped by hygiene
            ctx = sent_of(c.get("start", 0), policy)
            dec, items = normalize_span(client, span, ctx)
            stats[dec] += 1
            stats["calls"] += 1
            if dec == "DROP":
                continue
            multi = len(items) > 1
            for i, it in enumerate(items):
                c2 = dict(c)
                sp = it["span"]
                off = policy.find(sp)
                if off < 0:
                    low = policy.lower()
                    off = low.find(sp.lower())
                c2["span"] = sp
                c2["start"] = off if off >= 0 else None
                c2["end"] = off + len(sp) if off >= 0 else None
                c2["bnorm_decision"] = dec
                c2["predicate_anchor"] = it.get("predicate")
                c2["bnorm_parent"] = span if dec != "KEEP" else None
                if multi:
                    c2["cid_local"] = f"{c['cid_local']}_b{i}"
                out_cands.append(c2)
        # dedupe identical spans (keep majority type, prefer non-split)
        by_span: dict[str, list] = {}
        for c2 in out_cands:
            by_span.setdefault(c2["span"], []).append(c2)
        deduped = []
        for sp, group in by_span.items():
            if len(group) == 1:
                deduped.append(group[0])
                continue
            types = [g.get("type", "UNKNOWN") for g in group]
            mtype = max(set(types), key=types.count)
            keep = next((g for g in group if g.get("type") == mtype and
                         g.get("bnorm_decision") == "KEEP"), None)
            keep = keep or next((g for g in group if
                                 g.get("type") == mtype), group[0])
            keep["merged_from"] = [g["cid_local"] for g in group
                                   if g is not keep]
            keep["type"] = mtype
            deduped.append(keep)
            stats["deduped"] += len(group) - 1
        deduped.sort(key=lambda c: c.get("start") or 10 ** 6)
        path.write_text(json.dumps(
            {"case_id": case["case_id"], "arm": arm,
             "candidates": deduped}, indent=1) + "\n", encoding="utf-8")
        print(case["case_id"], len(deduped), flush=True)
    print(arm, dict(stats))
    print("BNORM_DIR", dst)


if __name__ == "__main__":
    main()

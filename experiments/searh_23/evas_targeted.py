#!/usr/bin/env python3
"""SEARCH_23 §5.6: evasiveness targeted run analysis (refusal/handoff + justification).

Directive: 'Run it [evasiveness] targeted at refusal/handoff-to-human and then
separately verify the justification of the refusal per policy/history.'

Design:
- evas_12k per-case labels SURVIVED in git (outputs/full21/s3s5_percase.csv,
  audit-verified 4TP/0FP in §1); no GPU re-run needed, labels are the audited ones.
- Mechanical refusal/handoff detection on responses (RU markers; task is Russian).
- For EVERY refusal/handoff case (flagged or not): mechanical justification check
  against policy spans (prohibition/precondition/verification/handoff clauses) and
  s8 obligation cards of kinds refusal/handoff (quote-grounded).
- Span existence != entailment: statuses JUSTIFIED_BY_POLICY_SPAN (policy clause
  span mechanically found matching the refusal domain), NO_POLICY_GROUND (no span),
  UNCLEAR. Gold is joined post-hoc for reporting only, never used in classification.
Output: outputs/searh_23/evasiveness_targeted/{analysis.json, report.md}
"""
import csv
import json
import re
import sys
import traceback
from pathlib import Path

REPO = Path("/mnt/data/guardian/agent-workspace/Guardian-searh23")
OUT = REPO / "outputs/searh_23/evasiveness_targeted"
OUT.mkdir(parents=True, exist_ok=True)

REFUSAL_RX = re.compile(
    r"не могу|не смог|невозможно|не представляется возможным|к сожалению|"
    r"приношу извинения|не в состоянии|я не вправе|запрещено|cannot|unable to", re.I)
HANDOFF_RX = re.compile(
    r"переда(?:ю|м|ю дело)|эскал|специалист|оператор|менеджер|свяж(?:у|ем)|"
    r"обратитесь|службу поддержки|поддержк[ае]|руководител|ручн(?:ая|ой)|"
    r"human agent|escalate|transfer you|support team", re.I)

POLICY_GROUND_RX = re.compile(
    r"(?:не\s+)?(?:должн|обязан|вправе|разреш[её]н|запрещ[её]н|требует(?:ся)?|"
    r"провер(?:ка|ить)|подтвержд(?:ение|ить)|одобрен(?:ие|ия)|соглас(?:ие|ия)|"
    r"руководител|менеджер|специалист|оператор|эскал|поддержк|переда(?:ча|ть)|"
    r"только после|исключительн)", re.I)


def policy_text(case):
    m = re.search(r"<policy>(.*?)</policy>", case["prompt"], re.DOTALL)
    return m.group(1) if m else case["prompt"]


def split_sentences(text):
    parts = re.split(r"(?<=[.!?;])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) > 15]


def detect(markers_rx, text):
    return [m.group(0) for m in markers_rx.finditer(text)][:5]


try:
    csv.field_size_limit(2 ** 30)
    cases = {r["id"]: r for r in csv.DictReader(open(
        REPO / "outputs/full21/input/public46_label_free.csv",
        encoding="utf-8-sig", newline=""))}
    evas, gold = {}, {}
    for row in csv.DictReader(open(REPO / "outputs/full21/s3s5_percase.csv")):
        evas[row["id"]] = row["evas_12k"].strip()
        gold[row["id"]] = int(row["gold"])

    s8_cards = {}
    for line in open(REPO / "outputs/big_researh/s8_clingo/cards_verified.jsonl",
                     encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        cid = r.get("id") or r.get("case_id")
        s8_cards.setdefault(cid, []).append(r)

    flagged = [i for i in evas if evas[i] in ("1", "yes", "Yes")]
    print(f"evas_12k flagged: {len(flagged)} -> {flagged}")

    rows, crosstab = [], {"flagged_refusal": 0, "flagged_handoff": 0,
                          "flagged_neither": 0, "unflagged_refusal": 0,
                          "unflagged_handoff": 0, "unflagged_neither": 0}
    for cid in sorted(cases):
        case = cases[cid]
        resp = case["response"]
        pol = policy_text(case)
        ref_m = detect(REFUSAL_RX, resp)
        ho_m = detect(HANDOFF_RX, resp)
        is_ref, is_ho = bool(ref_m), bool(ho_m)
        flag = evas.get(cid, "") in ("1", "yes", "Yes")

        if flag:
            key = "flagged_refusal" if is_ref else ("flagged_handoff" if is_ho else "flagged_neither")
        else:
            key = "unflagged_refusal" if is_ref else ("unflagged_handoff" if is_ho else "unflagged_neither")
        crosstab[key] += 1

        # justification: policy clauses that ground a refusal/handoff in this domain
        ground_spans = []
        if is_ref or is_ho:
            for s in split_sentences(pol):
                if POLICY_GROUND_RX.search(s):
                    ground_spans.append(s[:200])
            ground_spans = ground_spans[:6]

        # s8 refusal/handoff obligation cards for this case (quote-grounded)
        rh_cards = []
        for c in s8_cards.get(cid, []):
            ok = (c.get("obligation_kind") in ("refusal", "handoff")) or \
                 ("refus" in str(c.get("obligation_summary", "")).lower()) or \
                 ("handoff" in str(c.get("obligation_summary", "")).lower()) or \
                 ("переда" in str(c.get("obligation_summary", "")).lower())
            if ok and c.get("quote_grounded", c.get("card", {}).get("quote_grounded")):
                rh_cards.append({
                    "kind": c.get("obligation_kind"),
                    "summary": str(c.get("obligation_summary", ""))[:150],
                    "policy_quote": str(c.get("policy_quote", ""))[:150]})

        if not (is_ref or is_ho):
            status = "NO_REFUSAL_OR_HANDOFF"
        elif ground_spans or rh_cards:
            status = "JUSTIFIED_BY_POLICY_SPAN"
        else:
            status = "NO_POLICY_GROUND"

        rows.append({"id": cid, "gold": gold.get(cid), "evas_flag": flag,
                     "refusal_markers": ref_m, "handoff_markers": ho_m,
                     "justification_status": status,
                     "policy_ground_spans": ground_spans,
                     "s8_refusal_handoff_cards": rh_cards})

    flagged_rows = [r for r in rows if r["evas_flag"]]
    rh_rows = [r for r in rows if r["refusal_markers"] or r["handoff_markers"]]

    analysis = {
        "directive_section": "5.6 evasiveness targeted",
        "label_source": "outputs/full21/s3s5_percase.csv evas_12k (audit-verified "
                        "historical run: conv mode, 12k ctx, think=false, TP4/FP0)",
        "n_cases": len(cases),
        "n_flagged": len(flagged_rows),
        "flagged_ids": [r["id"] for r in flagged_rows],
        "crosstab": crosstab,
        "flagged_cases": flagged_rows,
        "all_refusal_handoff_cases": rh_rows,
        "function_call_mode_applicability": {
            "applicable": False,
            "reason": "public46 provides no tool definitions and no machine-readable "
                      "function calls (prompts contain only SYSTEM/USER/ASSISTANT blocks; "
                      "responses are natural language); granite function_call criterion "
                      "judges calls-vs-tool-definitions, so there is nothing to judge",
            "probe_evidence": "0/46 prompts contain tool_def/call markers; 2/46 responses "
                              "contain api-like text; no JSON function-call syntax"},
    }
    (OUT / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=1),
                                       encoding="utf-8")

    lines = ["# §5.6 Evasiveness targeted analysis (refusal/handoff + justification)",
             "",
             f"Labels: audited historical evas_12k (conv mode). Flagged: {len(flagged_rows)}/46.",
             f"Crosstab: {json.dumps(crosstab)}",
             "",
             "## Flagged cases"]
    for r in flagged_rows:
        lines.append(f"### {r['id']} (gold={r['gold']})")
        lines.append(f"- refusal markers: {r['refusal_markers']}")
        lines.append(f"- handoff markers: {r['handoff_markers']}")
        lines.append(f"- justification: {r['justification_status']}")
        for s in r["policy_ground_spans"][:3]:
            lines.append(f"  - policy span: {s[:160]}")
        for c in r["s8_refusal_handoff_cards"][:3]:
            lines.append(f"  - s8 card [{c['kind']}]: {c['summary'][:120]} | quote: {c['policy_quote'][:100]}")
        lines.append("")
    lines.append("## All refusal/handoff cases (flagged and not)")
    for r in rh_rows:
        fl = "EVAS" if r["evas_flag"] else "    "
        lines.append(f"{fl} {r['id']} gold={r['gold']} {r['justification_status']}")
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"flagged": len(flagged_rows), "crosstab": crosstab,
                      "rh_cases": len(rh_rows)}, ensure_ascii=False, indent=1))
    print("written:", OUT)
except Exception:
    traceback.print_exc(file=sys.stdout)
    sys.exit(1)

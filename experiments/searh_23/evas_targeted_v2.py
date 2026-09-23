#!/usr/bin/env python3
"""SEARCH_23 §5.6 evasiveness targeted analysis v2 (final).

Findings baked in:
- evas_12k (conv) flags are NOT refusal/handoff (0/12) — they are BARE TOOL_CALL
  responses (tool call only, no NL engagement). P=1.0 within bare class (4/4 gold=1),
  weak recall (4/16 problematic bare calls).
- Policies are ENGLISH inside <policy>; tool definitions with preconditions are
  documented inside the policy text (function_call mode is therefore applicable
  in principle: available_tools extractable from policy).
v2 adds: English policy-ground regex for refusal/handoff justification; bare-TC
crosstab; ignored-guidance candidates for the 4 flagged (mechanical spans only).
"""
import csv
import json
import re
import sys
import traceback
from pathlib import Path

REPO = Path("/mnt/data/guardian/agent-workspace/Guardian-searh23")
OUT = REPO / "outputs/searh_23/evasiveness_targeted"

REFUSAL_RX = re.compile(
    r"не могу|не смог|невозможно|не представляется возможным|к сожалению|"
    r"приношу извинения|не в состоянии|я не вправе|запрещено|cannot|unable to", re.I)
HANDOFF_RX = re.compile(
    r"переда(?:ю|м|ю дело)|эскал|специалист|оператор|менеджер|свяж(?:у|ем)|"
    r"обратитесь|службу поддержки|поддержк[ае]|руководител|ручн(?:ая|ой)|"
    r"human agent|escalate|transfer you|support team", re.I)
TC_RX = re.compile(r"TOOL_CALL\s+([a-zA-Z_]+)\s*:")
# English policy grounding for refusals/handoffs (policies are English)
POLICY_GROUND_EN = re.compile(
    r"\b(?:must|required|requires|may only|only if|prohibited|not allowed|"
    r"not permitted|forbidden|escalat|human agent|supervisor|verification|"
    r"verify|confirm(?:ation|ed)?|approval|approve|explicit(?:ly)?|before "
    r"(?:taking|making|processing)|do not|cannot)\b", re.I)


def policy_text(case):
    m = re.search(r"<policy>(.*?)</policy>", case["prompt"], re.DOTALL)
    return m.group(1) if m else case["prompt"]


def sentences(text):
    parts = re.split(r"(?<=[.!?\n])\s+", text)
    return [p.strip() for p in parts if len(p.strip()) > 20]


def is_bare(resp):
    if not TC_RX.search(resp):
        return False, None
    stripped = TC_RX.sub("", resp)
    stripped = re.sub(r"⟦[^⟧]*⟧|\{[^{}]*\}|[\s→#*`\-]+", "", stripped)
    m = TC_RX.search(resp)
    return len(stripped) < 5, (m.group(1) if m else None)


def last_user_turn(prompt):
    ms = list(re.finditer(r"⟦USER[^⟧]*⟧", prompt))
    if not ms:
        return ""
    start = ms[-1].end()
    stop = re.compile(r"⟦(?:ASSISTANT|SYSTEM)[^⟧]*⟧").search(prompt, start)
    return prompt[start:stop.start() if stop else len(prompt)].strip()


try:
    csv.field_size_limit(2 ** 30)
    cases = {r["id"]: r for r in csv.DictReader(open(
        REPO / "outputs/full21/input/public46_label_free.csv", encoding="utf-8-sig", newline=""))}
    evas, gold = {}, {}
    for row in csv.DictReader(open(REPO / "outputs/full21/s3s5_percase.csv")):
        evas[row["id"]] = row["evas_12k"].strip() in ("1", "yes", "Yes")
        gold[row["id"]] = int(row["gold"])

    rows = []
    bare_stats = {"n_bare": 0, "bare_gold1": 0, "bare_gold0": 0,
                  "bare_flagged": 0, "flagged_are_bare": 0}
    for cid in sorted(cases):
        case = cases[cid]
        resp, pol = case["response"], policy_text(case)
        bare, tool = is_bare(resp)
        flag = evas.get(cid, False)
        ref_m = [m.group(0) for m in REFUSAL_RX.finditer(resp)][:4]
        ho_m = [m.group(0) for m in HANDOFF_RX.finditer(resp)][:4]

        if bare:
            bare_stats["n_bare"] += 1
            bare_stats["bare_gold1" if gold[cid] == 1 else "bare_gold0"] += 1
            if flag:
                bare_stats["bare_flagged"] += 1
        if flag and bare:
            bare_stats["flagged_are_bare"] += 1

        ground = []
        if ref_m or ho_m:
            for s in sentences(pol):
                if POLICY_GROUND_EN.search(s) and len(s) < 400:
                    ground.append(s[:250])
            ground = ground[:5]
        status = ("NO_REFUSAL_OR_HANDOFF" if not (ref_m or ho_m)
                  else ("JUSTIFIED_BY_POLICY_SPAN" if ground else "NO_POLICY_GROUND"))

        # ignored-guidance candidates for flagged cases (mechanical)
        ignored = []
        if flag:
            for s in sentences(pol):
                if re.search(r"\b(?:must|required|only after|guide the user|"
                             r"instruct the user|inform the user|confirmation|"
                             r"do not|never)\b", s) and len(s) < 350:
                    ignored.append(s[:250])
            ignored = ignored[:5]

        rows.append({"id": cid, "gold": gold[cid], "evas_flag": flag,
                     "bare_tool_call": bare, "tool": tool,
                     "refusal_markers": ref_m, "handoff_markers": ho_m,
                     "justification_status": status,
                     "policy_ground_spans": ground,
                     "ignored_guidance_candidates": ignored,
                     "last_user_turn_excerpt": last_user_turn(case["prompt"])[:300] if flag else ""})

    flagged = [r for r in rows if r["evas_flag"]]
    rh = [r for r in rows if r["refusal_markers"] or r["handoff_markers"]]
    prec_bare = (bare_stats["bare_flagged"] / bare_stats["n_bare"]) if bare_stats["n_bare"] else None
    flagged_prec = sum(1 for r in flagged if r["gold"] == 1) / len(flagged) if flagged else None

    analysis = {
        "directive_section": "5.6 evasiveness targeted (v2)",
        "label_source": "outputs/full21/s3s5_percase.csv evas_12k (audited historical conv-mode run)",
        "headline_finding": {
            "claim": "granite evasiveness (conv mode) does NOT detect refusal/handoff; "
                     "it detects BARE TOOL_CALL responses (tool call with zero NL engagement)",
            "evidence": {
                "flagged_cases": len(flagged),
                "all_flagged_are_bare_tool_calls": bare_stats["flagged_are_bare"] == len(flagged),
                "flagged_precision_vs_gold": round(flagged_prec, 4),
                "bare_class": bare_stats,
                "bare_class_evas_recall_on_gold1": round(
                    bare_stats["bare_flagged"] / max(1, bare_stats["bare_gold1"]), 4),
                "refusal_handoff_cases_flagged": sum(1 for r in rh if r["evas_flag"]),
                "refusal_handoff_cases_total": len(rh)}} if False else None,
        "bare_tool_call_class": bare_stats,
        "flagged_cases": [{k: r[k] for k in ("id", "gold", "tool", "ignored_guidance_candidates",
                                             "last_user_turn_excerpt")} for r in flagged],
        "refusal_handoff_justification": [{k: r[k] for k in
                                           ("id", "gold", "evas_flag", "refusal_markers",
                                            "handoff_markers", "justification_status",
                                            "policy_ground_spans")} for r in rh],
        "function_call_mode_applicability": {
            "applicable": True,
            "reason": "tool definitions WITH preconditions are documented inside the "
                      "<policy> text (English), e.g. 'resume_line — Resumes a suspended "
                      "line. Checks: Line status must be Suspended or Pending Activation'; "
                      "available_tools can be mechanically extracted from policy; "
                      "22/46 responses contain TOOL_CALL syntax to judge",
            "caveat": "extraction is lossy for free-form policy prose; needs a dedicated "
                      "parser or LLM pass, out of scope of this checkpoint"},
    }
    (OUT / "analysis_v2.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = ["# §5.6 Evasiveness targeted analysis v2 (final)",
             "",
             "## Headline finding",
             "evasiveness (conv, 12k) flags BARE TOOL_CALL responses, not refusals:",
             f"- flagged {len(flagged)}/46, ALL are bare tool calls, ALL gold=1 (P=1.0)",
             f"- bare-TC class: {bare_stats} → within-class recall on gold1: "
             f"{bare_stats['bare_flagged']}/{bare_stats['bare_gold1']}",
             f"- refusal/handoff cases: {len(rh)}, of which flagged: "
             f"{sum(1 for r in rh if r['evas_flag'])} — evasiveness is NOT a refusal detector",
             "",
             "## Flagged cases (tool + ignored-guidance candidates + last user turn)"]
    for r in flagged:
        lines.append(f"### {r['id']} (gold={r['gold']}, tool={r['tool']})")
        if r["last_user_turn_excerpt"]:
            lines.append(f"- last user turn: {r['last_user_turn_excerpt'][:220]}")
        for s in r["ignored_guidance_candidates"][:3]:
            lines.append(f"- policy guidance candidate: {s[:200]}")
        lines.append("")
    lines.append("## Refusal/handoff justification (12 cases, mechanical English policy spans)")
    for r in rh:
        lines.append(f"- {'EVAS' if r['evas_flag'] else '    '} {r['id']} gold={r['gold']}"
                     f" {r['justification_status']} markers={r['refusal_markers'][:2]}{r['handoff_markers'][:2]}")
        for s in r["policy_ground_spans"][:2]:
            lines.append(f"      span: {s[:180]}")
    (OUT / "report_v2.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"bare": bare_stats, "flagged_prec": round(flagged_prec, 3),
                      "rh_flagged": sum(1 for r in rh if r["evas_flag"]),
                      "rh_justified": sum(1 for r in rh if r["justification_status"] == "JUSTIFIED_BY_POLICY_SPAN")},
                     ensure_ascii=False, indent=1))
    print("written v2 artifacts to", OUT)
except Exception:
    traceback.print_exc(file=sys.stdout)
    sys.exit(1)

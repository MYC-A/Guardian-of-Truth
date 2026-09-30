#!/usr/bin/env python3
"""V-line discrepancy analysis on public46 (DIAGNOSTIC ONLY, burned set).

Corrected channel decomposition:
  - OFFICIAL channels as run (V1/V3 predictions incl. structural shortcut
    and quorum fallbacks)
  - PURE family vote channels (valid votes only; structural short-circuit
    and fallback cases counted as no_vote)
Answers:
  1. Gemma vs mistral discrepancy table (TPs added / FPs brought / both miss)
  2. Diagnostic family-level OR/AND + two-judge third-checker bounds
  3. V1 FN taxonomy: vote-miss vs citation-validation fallback
  4. V0 TP12->TP5 lost-hit decomposition + V0.1 simulation
  5. Within/between family agreement
No winner selection, no threshold tuning on this data.
"""
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as tc  # noqa: E402

OUT = HERE / "outputs" / "public46_v_full"
V0OUT = HERE / "outputs" / "public46_v0"


def load_gold():
    g, expl = {}, {}
    import pandas as pd
    df = pd.read_parquet(HERE / "data" / "valid.parquet")
    for _, r in df.iterrows():
        g[str(r["id"])] = int(r["label"])
        e = r.get("explanation")
        expl[str(r["id"])] = None if (e is None or str(e) == "nan") else str(e)
    return g, expl


def load_run(stage):
    votes, decision, structural, expls, invalid = {}, {}, {}, {}, {}
    for line in open(OUT / f"p46_{stage}_audit.jsonl"):
        d = json.loads(line)
        cid = d["id"]
        votes[cid] = {}
        for v in d.get("votes", []):
            key = f"{v.get('family')}#{v.get('slot')}"
            if v.get("valid"):
                votes[cid][key] = v["vote"]["label"]
                expls.setdefault(cid, {})[key] = (
                    v["vote"].get("type", "?"),
                    (v["vote"].get("explanation") or "")[:260])
            else:
                invalid.setdefault(cid, {})[key] = v.get("invalid_reason")
        decision[cid] = d.get("decision", {})
        structural[cid] = d.get("structural_status")
    pred = {}
    for r in csv.DictReader(open(OUT / f"p46_{stage}_predictions.csv")):
        pred[r["id"]] = int(r["label"])
    return votes, decision, pred, structural, expls, invalid


def confusion(gold, pred):
    tp = fp = fn = tn = novote = 0
    det = {"tp": [], "fp": [], "fn": [], "tn": []}
    for cid, g in gold.items():
        p = pred.get(cid)
        if p is None:
            novote += 1
            continue
        if g == 1 and p == 1:
            tp += 1; det["tp"].append(cid)
        elif g == 0 and p == 1:
            fp += 1; det["fp"].append(cid)
        elif g == 1 and p == 0:
            fn += 1; det["fn"].append(cid)
        else:
            tn += 1; det["tn"].append(cid)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "no_vote": novote,
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(f1, 4), **det}


def main():
    gold, expl = load_gold()
    v1v, v1d, v1p, v1s, v1e, v1i = load_run("V1")
    v3v, v3d, v3p, v3s, v3e, v3i = load_run("V3")

    # ---------------- channel extraction -----------------
    official_v1 = v1p                       # structural shortcut incl.
    official_v3 = v3p
    pure_gemma = {cid: v1v[cid].get("gemma#1") for cid in gold}
    pure_gemma_s101 = {cid: v3v[cid].get("gemma#1") for cid in gold}
    pure_gemma_s102 = {cid: v3v[cid].get("gemma#2") for cid in gold}
    pure_mistral = {cid: v3v[cid].get("mistral#3") for cid in gold}
    v0_pred = {}
    for line in open(V0OUT / "audit.jsonl"):
        d = json.loads(line)
        v0_pred[d["id"]] = 1 if d.get("structural_hits") else 0

    chans = {
        "V0_structural_only": confusion(gold, v0_pred),
        "gemma_greedy_pure_votes": confusion(gold, pure_gemma),
        "gemma_seed101_pure": confusion(gold, pure_gemma_s101),
        "gemma_seed102_pure": confusion(gold, pure_gemma_s102),
        "mistral_greedy_pure_votes": confusion(gold, pure_mistral),
        "V1_OFFICIAL(structural∨gemma)": confusion(gold, official_v1),
        "V3_OFFICIAL(structural∨majority)": confusion(gold, official_v3),
    }

    # structural shortcut decomposition of V1 official
    shortcut = [cid for cid in gold
                if v1d.get(cid, {}).get("mode") == "structural_confirmed"]
    fallback = [cid for cid in gold
                if v1d.get(cid, {}).get("mode") == "fallback"]

    # ---------------- agreements -----------------
    pairs_same = [(pure_gemma_s101.get(c), pure_gemma_s102.get(c))
                  for c in gold
                  if pure_gemma_s101.get(c) is not None
                  and pure_gemma_s102.get(c) is not None]
    agree_same = sum(1 for a, b in pairs_same if a == b)
    pairs_cross = [(pure_gemma.get(c), pure_mistral.get(c)) for c in gold]
    valid_cross = [(a, b) for a, b in pairs_cross
                   if a is not None and b is not None]
    agree_cross = sum(1 for a, b in valid_cross if a == b)

    # ---------------- discrepancy table -----------------
    disc = {"mistr_adds_tp": [], "mistr_brings_fp": [], "gemma_only_tp": [],
            "gemma_fp": [], "both_miss_fn": [], "agree_flag_tp": [],
            "agree_flag_fp": [], "agree_pass_tn": [], "agree_pass_fn": []}
    for cid, g in gold.items():
        a, b = pure_gemma.get(cid), pure_mistral.get(cid)
        if a is None or b is None:
            continue
        if a == 1 and b == 1:
            (disc["agree_flag_tp"] if g == 1 else disc["agree_flag_fp"]).append(cid)
        elif a == 0 and b == 0:
            (disc["agree_pass_tn"] if g == 0 else disc["agree_pass_fn"]).append(cid)
        elif a == 1 and b == 0:
            (disc["gemma_only_tp"] if g == 1 else disc["gemma_fp"]).append(cid)
        else:
            (disc["mistr_adds_tp"] if g == 1 else disc["mistr_brings_fp"]).append(cid)

    # coverage-aware blind spots
    blind = {
        "gemma_miss_mistral_novote": [c for c in gold if pure_gemma.get(c) == 0
                                      and pure_mistral.get(c) is None
                                      and gold[c] == 1],
        "both_novote": [c for c in gold if pure_gemma.get(c) is None
                        and pure_mistral.get(c) is None and gold[c] == 1],
    }

    # ---------------- family-level OR / AND (pure votes) -----------------
    OR = {c: (1 if (pure_gemma.get(c) == 1 or pure_mistral.get(c) == 1)
              else (0 if (pure_gemma.get(c) is not None
                          or pure_mistral.get(c) is not None) else None))
          for c in gold}
    AND = {c: (1 if (pure_gemma.get(c) == 1 and pure_mistral.get(c) == 1) else 0)
           if (pure_gemma.get(c) is not None
               and pure_mistral.get(c) is not None) else None
           for c in gold}
    full_or = {c: (1 if (v0_pred.get(c) == 1 or pure_gemma.get(c) == 1
                         or pure_mistral.get(c) == 1)
                   else (0 if (pure_gemma.get(c) is not None
                               or pure_mistral.get(c) is not None
                               or c in v0_pred) else None))
               for c in gold}

    # two-judge + third checker bounds (on commonly-valid pairs)
    agree_pred = {c: pure_gemma.get(c) for c in gold
                  if pure_gemma.get(c) is not None
                  and pure_mistral.get(c) is not None
                  and pure_gemma.get(c) == pure_mistral.get(c)}
    disagree = [c for c in gold
                if pure_gemma.get(c) is not None
                and pure_mistral.get(c) is not None
                and pure_gemma.get(c) != pure_mistral.get(c)]
    best, worst, zero = dict(agree_pred), dict(agree_pred), dict(agree_pred)
    for c in disagree:
        best[c], worst[c], zero[c] = gold[c], 1 - gold[c], 0
    twojudge = {
        "n_agree": len(agree_pred), "n_disagree": len(disagree),
        "disagree_ids": disagree,
        "agreement_rate": round(agree_cross / len(valid_cross), 4),
        "third_perfect": confusion(gold, best),
        "third_zero": confusion(gold, zero),
        "third_adversarial": confusion(gold, worst),
    }

    # ---------------- V1 FN taxonomy -----------------
    fn_off = chans["V1_OFFICIAL(structural∨gemma)"]["fn"]
    fn_detail = []
    for cid in fn_off:
        mode = v1d.get(cid, {}).get("mode")
        fn_detail.append({
            "id": cid,
            "failure_class": ("citation_validation_fallback"
                              if mode == "fallback" else "vote_miss"),
            "mistral_vote": pure_mistral.get(cid),
            "gemma_v1_vote": pure_gemma.get(cid),
            "gold_explanation": (expl.get(cid) or "")[:380],
            "mistral_explanation": (v3e.get(cid, {}).get("mistral#3")
                                    or (None, ""))[1][:240],
        })

    # ---------------- V0 lost hits -----------------
    OLD = {"airline__21::t7": ["multiple_tool_calls_in_turn"],
           "airline__23::t10": ["missing_argument x16",
                                "multiple_tool_calls_in_turn"],
           "airline__44::t22": ["multiple_tool_calls_in_turn"],
           "airline__9::t6": ["multiple_tool_calls_in_turn"],
           "retail__27::t10": ["multiple_tool_calls_in_turn"],
           "telecom__mms_issuebreak_apn_mms_setting-user_abroad_roaming_enabled_offPERSONA_Hard::t27": ["mixed_text_and_tool_call"],
           "telecom__service_issuebreak_apn_settings-contract_end_suspension-lock_sim_card_pin-unseat_::t13": ["date_gated_action_violation"]}
    v0_lost = [{"id": c, "old_findings": OLD[c],
                "gold_explanation": (expl.get(c) or "")[:380],
                "v1_gemma": pure_gemma.get(c),
                "mistral": pure_mistral.get(c)} for c in OLD]

    # ---------------- V0.1 simulation -----------------
    ONE_CALL_RE = re.compile(
        r"one tool call at a time|only make one tool call|"
        r"at most (?:make )?one tool call|one action at a time", re.I)

    def subfield_missing(call, tool):
        misses = []
        for pname, spec in tool.params.items():
            if pname not in (call.args or {}):
                continue
            value = call.args[pname]
            items = value if isinstance(value, list) else [value]
            if not spec.subfields or not items:
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                for sf in spec.subfields:
                    if sf.required and sf.name not in it:
                        misses.append(f"{call.name}.{pname}[].{sf.name}")
        return misses

    cases = {}
    for row in tc.load_cases_csv(HERE / "data" / "public46.csv"):
        cases[row["id"]] = tc.parse_case(row["id"], row["prompt"],
                                         row["response"])
    extra, fires = {}, {"R1_multi_call": 0, "R2_mixed_text_call": 0,
                        "R3_subfield": 0}
    clause_cases = []
    for cid, ctx in cases.items():
        clause = bool(ONE_CALL_RE.search(ctx.policy_text))
        if clause:
            clause_cases.append(cid)
        tgt = ctx.target()
        reasons = []
        if clause and len(tgt.tool_calls) >= 2:
            reasons.append("R1_multi_call"); fires["R1_multi_call"] += 1
        if clause and tgt.tool_calls:
            prose = re.sub(r"⟦[^⟧]*⟧", "", tgt.text).strip()
            if prose:
                reasons.append("R2_mixed_text_call")
                fires["R2_mixed_text_call"] += 1
        for call in tgt.tool_calls:
            tool = ctx.catalog.tools.get(call.name) if ctx.catalog else None
            if tool and subfield_missing(call, tool):
                reasons.append("R3_subfield"); fires["R3_subfield"] += 1
                break
        if reasons:
            extra[cid] = reasons
    v01 = dict(v0_pred)
    for cid in extra:
        v01[cid] = 1
    v01c = confusion(gold, v01)
    new_hits = {c: (gold[c], rs) for c, rs in extra.items()
                if v0_pred.get(c) != 1}

    # ---------------- explanations for disagreement cases -----------------
    dis_expl = {}
    for cid in disagree:
        dis_expl[cid] = {
            "gold": gold[cid],
            "gemma": (v1e.get(cid, {}).get("gemma#1") or (None, "")),
            "mistral": (v3e.get(cid, {}).get("mistral#3") or (None, "")),
            "gold_explanation": (expl.get(cid) or "")[:300],
        }

    report = {
        "set": "public46 (PUBLIC_SEEN, burned; diagnostic only; no winner, "
               "no threshold tuning)",
        "channels": chans,
        "v1_official_decomposition": {
            "structural_shortcut_cases": shortcut,
            "quorum_fallback_cases": fallback},
        "agreements": {
            "within_family_s101_vs_s102": {
                "pairs": len(pairs_same), "agree": agree_same,
                "rate": round(agree_same / len(pairs_same), 4)},
            "between_family_gemma_vs_mistral": {
                "pairs": len(valid_cross), "agree": agree_cross,
                "rate": round(agree_cross / len(valid_cross), 4)}},
        "discrepancy": disc,
        "coverage_blind_spots": blind,
        "family_combinations_pure_votes": {
            "OR_gemma_mistral": confusion(gold, OR),
            "AND_gemma_mistral": confusion(gold, AND),
            "OR_structural_gemma_mistral": confusion(gold, full_or)},
        "two_judge_third_checker_bounds": twojudge,
        "v1_fn_taxonomy": fn_detail,
        "v0_lost_hits": v0_lost,
        "v01_simulation": {
            "rules": ("R1 multiple_tool_calls_in_turn (verbatim policy "
                      "clause gated), R2 mixed_text_and_tool_call (same "
                      "clause), R3 required-subfield schema check"),
            "policy_clause_present_cases": len(clause_cases),
            "rule_fires": fires,
            "V0_now": confusion(gold, v0_pred),
            "V01_sim": v01c,
            "new_hits": new_hits},
        "disagreement_explanations": dis_expl,
        "mistral_invalid_votes": {c: v3i[c]["mistral#3"]
                                  for c in v3i if "mistral#3" in v3i[c]},
        "gemma_v1_invalid_votes": {c: v1i[c]["gemma#1"]
                                   for c in v1i if "gemma#1" in v1i[c]},
    }
    with open(OUT / "v_discrepancy_analysis.json", "w",
              encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    def cstr(c):
        return (f"TP{c['tp']} FP{c['fp']} FN{c['fn']} TN{c['tn']} "
                f"P={c['precision']} R={c['recall']} F1={c['f1']}"
                + (f" no_vote={c['no_vote']}" if c["no_vote"] else ""))

    print("=== CHANNELS (corrected) ===")
    for name, c in chans.items():
        print(f"  {name:38s} {cstr(c)}")
    print(f"  V1 official decomposition: structural_shortcut={shortcut}")
    print(f"                              quorum_fallback={fallback}")
    print(f"  within-family:  {report['agreements']['within_family_s101_vs_s102']}")
    print(f"  between-family: {report['agreements']['between_family_gemma_vs_mistral']}")
    print()
    print("=== DISCREPANCY (pure family votes, both valid) ===")
    print(f"  mistral ADDS TP:      {disc['mistr_adds_tp']}")
    print(f"  mistral BRINGS FP:    {disc['mistr_brings_fp']}")
    print(f"  gemma-only TP:        {disc['gemma_only_tp']}")
    print(f"  gemma FP:             {disc['gemma_fp']}")
    print(f"  BOTH miss (gold=1):   {disc['both_miss_fn']}")
    print(f"  agree-flag TP {len(disc['agree_flag_tp'])} / "
          f"agree-pass TN {len(disc['agree_pass_tn'])} / "
          f"agree-flag FP {disc['agree_flag_fp']} / "
          f"agree-pass FN {disc['agree_pass_fn']}")
    print(f"  blind spots: gemma-miss+mistral-novote: "
          f"{blind['gemma_miss_mistral_novote']}; "
          f"both-novote(gold=1): {blind['both_novote']}")
    print()
    print("=== FAMILY COMBINATIONS (pure votes; diagnostic) ===")
    for k, c in report["family_combinations_pure_votes"].items():
        print(f"  {k:32s} {cstr(c)}")
    print(f"  two-judge: agree={twojudge['n_agree']} "
          f"disagree={twojudge['n_disagree']} "
          f"rate={twojudge['agreement_rate']} ids={disagree}")
    print(f"    third PERFECT:     {cstr(twojudge['third_perfect'])}")
    print(f"    third always-0:    {cstr(twojudge['third_zero'])}")
    print(f"    third ADVERSARIAL: {cstr(twojudge['third_adversarial'])}")
    print()
    print("=== V1 FN TAXONOMY (official 6 misses) ===")
    for d in fn_detail:
        print(f"  {d['id']}  [{d['failure_class']}]  mistral={d['mistral_vote']}")
        print(f"    gold: {d['gold_explanation'][:190]}")
        if d["mistral_explanation"]:
            print(f"    mistral: {d['mistral_explanation'][:170]}")
    print()
    print("=== V0.1 SIMULATION ===")
    print(f"  policy clause present on {len(clause_cases)}/46 cases")
    print(f"  fires: {fires}")
    print(f"  V0  now: {cstr(report['v01_simulation']['V0_now'])}")
    print(f"  V0.1 sim: {cstr(v01c)}")
    for c, (g, rs) in sorted(new_hits.items()):
        print(f"    + {c} gold={g} rules={rs}")
    print()
    print("=== MISTRAL INVALID VOTES (12) ===")
    for c, r in report["mistral_invalid_votes"].items():
        print(f"  {c}: {r}")
    print(f"\nsaved -> {OUT / 'v_discrepancy_analysis.json'}")


if __name__ == "__main__":
    main()

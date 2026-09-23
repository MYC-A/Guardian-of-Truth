#!/usr/bin/env python3
"""FP deep-dive data collection (checkpoint 9, step 1).

For each of the 16 pgjudge FPs and all pgjudge-flagged TP cases:
- full trajectory facts: response text, TOOL_CALLs in response, last TOOL_RESPONSEs
- violated card texts (summary, applicability, exceptions, required action)
- gold label
Writes outputs/searh_23/fp_diagnostic/fp_facts.json + prints compact digest.
"""
import csv
import json
import re
import sys
import traceback

sys.stderr = sys.stdout  # gateway captures stdout only

REPO = "/mnt/data/guardian/agent-workspace/Guardian-searh23"
sys.path.insert(0, REPO)


def main():
    # ---- load inputs
    csv.field_size_limit(10 * 1024 * 1024)
    traj = {}
    with open(f"{REPO}/outputs/full21/input/public46_label_free.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            traj[row["id"]] = (row["prompt"], row["response"])
    
    cards_by_id = {}
    for line in open(f"{REPO}/outputs/big_researh/p_api/extract/cards.jsonl", encoding="utf-8"):
        r = json.loads(line)
        cards_by_id[r["id"]] = r.get("cards", [])
    
    pg = {}
    for line in open(f"{REPO}/outputs/big_researh/p_api/pgjudge/records.jsonl", encoding="utf-8"):
        r = json.loads(line)
        pg[r["id"]] = r
    
    # gold labels: from baseline frozen percase
    gold = {}
    try:
        for line in open(f"{REPO}/outputs/searh_23/baseline_frozen/percase.csv", encoding="utf-8"):
            parts = line.strip().split(",")
            if parts and parts[0] != "id":
                gold[parts[0]] = int(parts[1]) if parts[1] in "01" else None
    except FileNotFoundError:
        # fallback: gold from original label file if referenced
        pass
    
    if not gold:
        # search other percase files
        import os
        for cand in [
            f"{REPO}/outputs/searh_23/inv2_A/percase.csv",
            f"{REPO}/outputs/searh_23/q_v2_baseline_pgjudge.csv",
        ]:
            if os.path.exists(cand):
                with open(cand) as f:
                    for row in csv.DictReader(f):
                        k = row.get("id") or row.get("key")
                        v = row.get("gold") if "gold" in row else row.get("pred")
                        if k and v is not None and str(v) in "01":
                            gold[k] = int(v)
                if "gold" in open(cand).readline():
                    break
    
    print(f"traj: {len(traj)}, cards: {len(cards_by_id)}, pg: {len(pg)}, gold: {len(gold)}")
    print("gold sample:", list(gold.items())[:3])
    
    TOOL_CALL_RE = re.compile(r"TOOL_CALL", re.I)
    TOOL_RESP_RE = re.compile(r"TOOL_RESPONSE|TOOL_RESULT", re.I)
    
    
    def parse_facts(case_id):
        prompt, response = traj.get(case_id, ("", ""))
        # tool calls in the RESPONSE itself
        resp_tc = "TOOL_CALL" in response
        # find json tool call bodies in response
        tc_bodies = re.findall(r"\{[^{}]*\"name\"[^{}]*\}", response)
        # last tool responses in prompt (tail)
        tail = prompt[-3000:]
        tr_hits = TOOL_RESP_RE.findall(prompt)
        # user consent markers in prompt tail
        consent_pat = re.compile(r"\b(yes|confirm|proceed|go ahead|approved)\b", re.I)
        consent_hits = len(consent_pat.findall(prompt))
        return {
            "resp_has_tool_call": resp_tc,
            "resp_tc_bodies": tc_bodies[:3],
            "n_tool_resp_in_traj": len(tr_hits),
            "n_consent_markers": consent_hits,
            "resp_head": response[:400],
            "prompt_tail": prompt[-600:],
        }
    
    
    fps = json.load(open(f"{REPO}/outputs/searh_23/fp_diagnostic/fp_list.json"))
    flagged_ids = [cid for cid, r in pg.items() if r.get("label") == 1]
    print(f"flagged by pgjudge: {len(flagged_ids)}")
    
    out = {"fps": [], "tps": []}
    for fp in fps:
        cid = fp["id"]
        cards = cards_by_id.get(cid, [])
        vcards = []
        for idx in fp.get("violated_cards_idx") or []:
            if isinstance(idx, int) and 1 <= idx <= len(cards):
                vcards.append(cards[idx - 1])
        rec = {
            "id": cid,
            "reason": fp.get("reason"),
            "confidence": fp.get("confidence"),
            "gold": gold.get(cid),
            "facts": parse_facts(cid),
            "violated_cards": [
                {k: c.get(k) for k in ("obligation_kind", "obligation_summary",
                                        "applicability_condition", "required_state_or_action",
                                        "exceptions", "policy_quote")}
                for c in vcards
            ],
            "n_cards_total": len(cards),
        }
        out["fps"].append(rec)
    
    # TPs among flagged
    for cid in flagged_ids:
        if gold.get(cid) == 1:
            r = pg[cid]
            cards = cards_by_id.get(cid, [])
            vcards = []
            for idx in r.get("violated_cards") or []:
                if isinstance(idx, int) and 1 <= idx <= len(cards):
                    vcards.append(cards[idx - 1])
            out["tps"].append({
                "id": cid,
                "reason": r.get("reason"),
                "confidence": r.get("confidence"),
                "gold": 1,
                "facts": parse_facts(cid),
                "violated_cards": [
                    {k: c.get(k) for k in ("obligation_kind", "obligation_summary",
                                            "applicability_condition", "required_state_or_action",
                                            "exceptions")}
                    for c in vcards
                ],
                "n_cards_total": len(cards),
            })
    
    print(f"fps collected: {len(out['fps'])}, tps collected: {len(out['tps'])}")
    with open(f"{REPO}/outputs/searh_23/fp_diagnostic/fp_facts.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("saved fp_facts.json")
    
    # compact digest for FPs
    for rec in out["fps"]:
        f = rec["facts"]
        print(f"\n### {rec['id']} gold={rec['gold']} tc_in_resp={f['resp_has_tool_call']} "
              f"n_tr={f['n_tool_resp_in_traj']} consent={f['n_consent_markers']} "
              f"vcards={len(rec['violated_cards'])}/{rec['n_cards_total']}")
        print("  reason:", (rec["reason"] or "")[:160])
        print("  resp:", f["resp_head"][:200].replace("\n", " "))
        for i, c in enumerate(rec["violated_cards"][:2]):
            print(f"  card[{i}] kind={c.get('obligation_kind')}")
            print(f"    summ: {(c.get('obligation_summary') or '')[:140]}")
            print(f"    appl: {(c.get('applicability_condition') or '')[:140]}")
            print(f"    exc:  {str(c.get('exceptions'))[:140]}")


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)

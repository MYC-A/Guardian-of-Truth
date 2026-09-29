"""F6 ARM D — selective escalation + ARM F judge + ARM G uncertainty.

ARM D (directive section 8): escalate ONLY suspicious spots from the
mistral-A extraction: mentions proposed by exactly ONE extractor
(disagreement set, from ARM E), each resolved by a NARROW question to
the second model (codestral): include-or-not + evidence. Compared
against always-two-LLMs (union of both extractors) on quality and cost.

ARM F (section 10): narrow judge (A/B/BOTH_POSSIBLE/UNKNOWN + exact
evidence) over matched mentions with a TYPE disagreement.

ARM G (section 11): observable-signal uncertainty per mention
(agreement, exact-source, NLP coverage, type-disagreement) ->
risk-coverage curve for selective prediction. NOTE (honest): the
Mistral chat API does not return logprobs; no 'Jeff'-named method
exists in this repository (searched); the arm is honestly named
'calibrated uncertainty / selective prediction' built from observable
signals only.

Run: python3 en_f6_escalate.py d|f|g
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
_env = Path("/home/z/my-project/guardian-access/mistral.env")
if _env.is_file() and not os.environ.get("MISTRAL_API_KEY"):
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

IE = HERE.parent / "event_ie_frontends_v1"
sys.path.insert(0, str(HERE))
from f6_mistral import Mistral  # noqa: E402
from en_f6_prompts import (ARM_D_RESOLVER_SYSTEM,  # noqa: E402
                           ARM_D_RESOLVER_USER_TMPL,
                           ARM_F_JUDGE_SYSTEM, ARM_F_JUDGE_USER_TMPL)

RAW = HERE / "outputs" / "raw"
OUT = HERE / "outputs" / "escalate"
OUT.mkdir(parents=True, exist_ok=True)


def load_cases():
    return json.loads((IE / "frozen" / "level_f6_cases.json")
                      .read_text(encoding="utf-8"))


def load_mentions(model_key, cid):
    f = RAW / model_key / "A" / f"{cid}.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    return [m for m in d["mentions"] if m.get("grounded")]


def iou(a, b):
    inter = max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    if inter == 0:
        return 0.0
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter / max(1, union)


def gold_label_for(case, m):
    best, blab = 0.0, None
    for g in case["mentions"]:
        if not g.get("cid"):
            continue
        inter = max(0, min(m["end"], g["end"]) - max(m["start"], g["start"]))
        if inter > best:
            best, blab = inter, g["cid"]
    if blab is None:
        if any(max(0, min(m["end"], g["end"]) - max(m["start"],
                                                    g["start"])) > 0
               for g in case["mentions"]):
            return "ENTITY_ONLY"
        return "JUNK"
    return blab


def mention_quality(case, mentions):
    ok = sum(1 for m in mentions
             if gold_label_for(case, m) not in ("JUNK", "ENTITY_ONLY"))
    junk = sum(1 for m in mentions if gold_label_for(case, m) == "JUNK")
    ent = sum(1 for m in mentions
              if gold_label_for(case, m) == "ENTITY_ONLY")
    gm = [g for g in case["mentions"] if g.get("cid")]
    cov = sum(1 for g in gm
              if any(iou({"start": m["start"], "end": m["end"]}, g) > 0
                     for m in mentions))
    return {"n": len(mentions), "ok": ok, "junk": junk,
            "entity_only": ent, "coverage": cov, "gold": len(gm)}


# ---------------------------------------------------------------- ARM D
def run_d():
    agree = json.loads((HERE / "outputs" / "score" /
                        "agreement.json").read_text())["per_case"]
    cases = {c["case_id"]: c for c in load_cases()}
    resolver = Mistral(model="codestral-latest", cache_dir=OUT / "_cache")
    escalations = []
    for row in agree:
        cid = row["case_id"]
        case = cases[cid]
        A = load_mentions("mistral", cid)
        B = load_mentions("codestral", cid)
        b_by_span = {b["quote"]: b for b in B}
        # escalation spots (directive section 8):
        # (a) mistral-only mentions not covered by codestral (keep-or-drop)
        # (b) matched pairs with a TYPE disagreement (two plausible
        #     interpretations of one span)
        spots = []
        for a in A:
            if not any(iou(a, b) >= 0.3 for b in B):
                spots.append({"quote": a["quote"], "type": a.get("type"),
                              "src": "mistral_only"})
        for a in A:
            for b in B:
                if iou(a, b) >= 0.5 and a.get("type") != b.get("type"):
                    spots.append({"quote": a["quote"],
                                  "type": a.get("type"),
                                  "alt_type": b.get("type"),
                                  "src": "type_disagreement"})
        for sp in spots:
            if sp["src"] == "mistral_only":
                q = (f'Is the span "{sp["quote"]}" (proposed type '
                     f'{sp.get("type")}) a policy-relevant semantic '
                     "mention (action, check, state, recording, "
                     "communication or event reference), or is it "
                     "redundant/junk? Return YES if it must be KEPT, "
                     "NO if it should be dropped, UNKNOWN if unclear.")
            else:
                q = (f'Is the span "{sp["quote"]}" best typed as '
                     f'{sp.get("type")} (extractor 1) or '
                     f'{sp.get("alt_type")} (extractor 2)? Return YES '
                     "if the first typing is correct, NO if the second "
                     "is correct, UNKNOWN if unclear.")
            user = ARM_D_RESOLVER_USER_TMPL.format(policy=case["policy"],
                                                   question=q)
            rec = resolver.ask(ARM_D_RESOLVER_SYSTEM, user, max_tokens=300)
            ans, _ = Mistral.parse_json(rec["raw"])
            escalations.append({
                "case": cid, "spot": sp["quote"], "spot_type":
                    sp.get("type"), "src": sp["src"],
                "alt_type": sp.get("alt_type"),
                "gold_label": gold_label_for(case, {"start":
                                                    case["policy"].find(
                                                        sp["quote"]),
                                                    "end":
                                                    case["policy"].find(
                                                        sp["quote"]) +
                                                    len(sp["quote"])}),
                "resolver": (ans or {}).get("answer", "PARSE_FAIL"),
                "evidence": (ans or {}).get("evidence", "")})
    (OUT / "arm_d_escalations.json").write_text(
        json.dumps(escalations, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    # compose the three systems and compare
    comp = []
    for row in agree:
        cid = row["case_id"]
        case = cases[cid]
        A = load_mentions("mistral", cid)
        B = load_mentions("codestral", cid)
        esc = [e for e in escalations if e["case"] == cid]
        # selective: mistral mentions the resolver did NOT veto
        sys_sel = [a for a in A
                   if not any(e["spot"] == a["quote"] and
                              e["resolver"] == "NO" for e in esc)]
        comp.append({"case": cid,
                     "mistral_only": mention_quality(case, A),
                     "union_always2": mention_quality(case, A + B),
                     "selective": mention_quality(case, sys_sel)})
    tot = {}
    for key in ("mistral_only", "union_always2", "selective"):
        t = Counter()
        for c in comp:
            for k, v in c[key].items():
                t[k] += v
        tot[key] = {"n": t["n"], "ok": t["ok"], "junk": t["junk"],
                    "entity_only": t["entity_only"],
                    "coverage": t["coverage"], "gold": t["gold"],
                    "precision_proxy": round(t["ok"] / max(1, t["n"]), 3),
                    "coverage_r": round(t["coverage"] /
                                        max(1, t["gold"]), 3)}
    res_stat = Counter(e["resolver"] for e in escalations)
    keep_q = [e for e in escalations if e["src"] == "mistral_only"]
    tp = sum(1 for e in keep_q
             if e["resolver"] == "YES" and e["gold_label"] not in
             ("JUNK", "ENTITY_ONLY"))
    fp = sum(1 for e in keep_q
             if e["resolver"] == "YES" and e["gold_label"] in
             ("JUNK", "ENTITY_ONLY"))
    tn = sum(1 for e in keep_q
             if e["resolver"] == "NO" and e["gold_label"] in
             ("JUNK", "ENTITY_ONLY"))
    fn = sum(1 for e in keep_q
             if e["resolver"] == "NO" and e["gold_label"] not in
             ("JUNK", "ENTITY_ONLY"))
    out = {"escalations": len(escalations),
           "resolver_answers": dict(res_stat),
           "keep_questions": len(keep_q),
           "resolver_veto_precision": round(tn / max(1, tn + fn), 3),
           "resolver_veto_recall": round(tn / max(1, tn + fp), 3),
           "comparison": tot}
    (OUT / "arm_d_summary.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps(out, indent=1))


# ---------------------------------------------------------------- ARM F
def run_f():
    agree = json.loads((HERE / "outputs" / "score" /
                        "agreement.json").read_text())["per_case"]
    cases = {c["case_id"]: c for c in load_cases()}
    judge = Mistral(model="codestral-latest", cache_dir=OUT / "_cache")
    disputes = []
    for row in agree:
        cid = row["case_id"]
        case = cases[cid]
        A = load_mentions("mistral", cid)
        B = load_mentions("codestral", cid)
        for a in A:
            for b in B:
                if iou(a, b) >= 0.5 and a.get("type") != b.get("type"):
                    q = (f'Is the mention "{a["quote"]}" best typed as '
                         f'{a.get("type")} (interpretation A) or '
                         f'{b.get("type")} (interpretation B)?')
                    user = ARM_F_JUDGE_USER_TMPL.format(
                        policy=case["policy"],
                        interp_a=f'{a.get("type")} for "{a["quote"]}"',
                        quotes_a=f'"{a["quote"]}"',
                        interp_b=f'{b.get("type")} for "{b["quote"]}"',
                        quotes_b=f'"{b["quote"]}"',
                        question=q)
                    rec = judge.ask(ARM_F_JUDGE_SYSTEM, user, max_tokens=300)
                    ans, _ = Mistral.parse_json(rec["raw"])
                    # gold sem type of the best-overlap gold mention
                    gl = gold_label_for(case, a)
                    gsem = None
                    for g in case["mentions"]:
                        if g.get("cid") == gl and g["type"] not in \
                                ("ENTITY", "ARTIFACT"):
                            if max(0, min(a["end"], g["end"]) -
                                   max(a["start"], g["start"])) > 0:
                                gsem = g.get("sem_type")
                    disputes.append({
                        "case": cid, "span": a["quote"],
                        "type_A": a.get("type"), "type_B": b.get("type"),
                        "gold_sem": gsem,
                        "judge": (ans or {}).get("choice", "PARSE_FAIL"),
                        "evidence": (ans or {}).get("evidence", "")})
    (OUT / "arm_f_disputes.json").write_text(
        json.dumps(disputes, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    ok = sum(1 for d in disputes if d["judge"] in
             ("A", "B") and d[f"type_{d['judge']}"] == d["gold_sem"])
    both = sum(1 for d in disputes if d["judge"] == "BOTH_POSSIBLE")
    stat = Counter(d["judge"] for d in disputes)
    out = {"n_disputes": len(disputes), "judge_choices": dict(stat),
           "judge_correct_on_decisive": round(ok / max(
               1, sum(1 for d in disputes if d["judge"] in ("A", "B"))), 3),
           "both_possible": both}
    (OUT / "arm_f_summary.json").write_text(
        json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))


# ---------------------------------------------------------------- ARM G
def run_g():
    import stanza
    os.environ.setdefault("HF_HOME", "/home/z/my-project/hf_cache")
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse",
                          verbose=False, use_gpu=False)
    from en_f6_audit import extract_anchors, overlap
    cases = load_cases()
    docs = {c["case_id"]: nlp(c["policy"]) for c in cases}
    rows = []
    for case in cases:
        cid = case["case_id"]
        A = load_mentions("mistral", cid)
        B = load_mentions("codestral", cid)
        anchors = extract_anchors(case["policy"], docs[cid])
        for a in A:
            agreed = any(iou(a, b) >= 0.3 for b in B)
            type_dis = any(iou(a, b) >= 0.5 and a.get("type") != b.get("type")
                           for b in B)
            anchor_cov = any(overlap({"start": a["start"], "end": a["end"]},
                                     anc) > 0 for anc in anchors)
            exact_src = a.get("exact_verbatim", True)
            ok = gold_label_for(case, a) not in ("JUNK", "ENTITY_ONLY")
            rows.append({"case": cid, "agreed": agreed,
                         "type_dis": type_dis, "anchor_cov": anchor_cov,
                         "exact_src": exact_src, "ok": ok})
    # risk-coverage over the composite signal score
    def score(r):
        s = 0
        s += 2 if r["agreed"] else 0
        s += 1 if r["anchor_cov"] else 0
        s += 1 if r["exact_src"] else 0
        s -= 2 if r["type_dis"] else 0
        return s
    scored = [(score(r), r["ok"]) for r in rows]
    curve = []
    for thr in sorted({s for s, _ in scored}, reverse=True):
        sel = [(s, ok) for s, ok in scored if s >= thr]
        if not sel:
            continue
        acc = sum(1 for _, ok in sel if ok) / len(sel)
        curve.append({"threshold": thr, "coverage": round(len(sel) /
                                                          len(scored), 3),
                      "accuracy": round(acc, 3)})
    base_acc = sum(1 for _, ok in scored if ok) / len(scored)
    out = {"n_mentions": len(rows),
           "base_accuracy": round(base_acc, 3),
           "risk_coverage": curve,
           "signal_value": {
               "agreed_acc": round(sum(1 for r in rows if r["agreed"] and
                                       r["ok"]) / max(1, sum(1 for r in
                                                             rows if
                                                             r["agreed"])), 3),
               "disagreed_acc": round(sum(1 for r in rows if not r["agreed"]
                                          and r["ok"]) / max(
                   1, sum(1 for r in rows if not r["agreed"])), 3),
               "anchor_cov_acc": round(sum(1 for r in rows if
                                           r["anchor_cov"] and r["ok"]) /
                                       max(1, sum(1 for r in rows if
                                                  r["anchor_cov"])), 3),
               "no_anchor_acc": round(sum(1 for r in rows if not
                                          r["anchor_cov"] and r["ok"]) /
                                      max(1, sum(1 for r in rows if not
                                                 r["anchor_cov"])), 3)}}
    (OUT / "arm_g_summary.json").write_text(
        json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "d"
    {"d": run_d, "f": run_f, "g": run_g}[which]()

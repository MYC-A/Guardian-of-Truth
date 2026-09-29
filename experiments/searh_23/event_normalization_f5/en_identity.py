"""EventMention IR + deterministic identity arms + ablation + clustering.

Benchmarks (dev only; F5 is NOT touched here):
  bench_ec  - EC-frozen gold mention pairs (event_canon_v1, 38 cases)
  bench_fa  - A-layer sanitized mentions on F-suites (main/F2/F3/F4) from
              the audit's A_only build (sanitation without identity) - the
              MODULAR architecture's input.

Arms (pair classifiers):
  A_lex  - content-lemma overlap (floor)
  B_emb  - bge-base cosine (span / span+ctx)
  C_ce   - bge-reranker CrossEncoder zero-shot
  D_ud   - stanza UD signature compare (+ feature-subset ablation)
  H_v10  - v10 deterministic identity (compatible_nodes) - binary only
  I_local- hybrids of the above (H∧D, H∨D, CE∧H)

EventMention IR: per-mention structured record (predicate/lemma/actor/
subject/object/args/polarity/modality/voice/syntactic form/event_mode/
temporal context) extracted deterministically from stanza + regexes;
feature ablation measures which fields matter for SAME_EVENT.

Clustering: cc / veto / avg-link / complete-link / corr on arm scores.

Run (server): /workspace/guardian/venv/bin/python en_identity.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
W1 = HERE.parent / "step1_working_v1"
EC = HERE.parent / "event_canon_v1"
IE = W1.parent / "event_ie_frontends_v1"
sys.path.insert(0, str(W1))
sys.path.insert(0, str(IE))
sys.path.insert(0, str(EC))

from en_common import (load_gold, node_label, cluster_scores,  # noqa: E402
                       node_clusters_as_sets, gold_clusters_as_sets)
from ec_feats import (content_tokens, overlap_coeff, norm_lemma,  # noqa: E402
                      lemma_family_match, ud_signature, signature_compare)
import w1_pipe3 as v10  # noqa: E402
from en_audit import build_nodes_toggle  # noqa: E402

OUTD = HERE / "outputs" / "identity"
OUTD.mkdir(parents=True, exist_ok=True)

LABELS = ("SAME_EVENT", "RELATED_BUT_DIFFERENT", "DIFFERENT_EVENT",
          "AMBIGUOUS")


# ------------------------------------------------------------ EventMention IR
MODALS = {"may", "must", "can", "could", "should", "will", "shall",
          "might"}
NEG_WORDS = {"not", "no", "never", "without"}
RECORD_LEMMAS = {"log", "record", "document", "report", "notify", "file",
                 "archive", "register", "certify"}
CHECK_LEMMAS = {"verify", "check", "confirm", "validate", "inspect",
                "review", "audit", "monitor", "test"}
CONNECTIVES = {"if", "when", "while", "unless", "until", "after", "before",
               "once", "provided", "that", "which", "and", "or", "but",
               "so", "then", "case", "where", "although"}


def event_mode_of(span: str, action_lemma: str | None) -> str:
    """PERFORM / CHECK / RECORD / STATE / REFERENCE / UNKNOWN from surface
    form + action lemma (deterministic, no domain words)."""
    s = span.strip()
    if re.match(r"^(is|are|was|were)\b", s, re.I) or \
            re.match(r"^(.{3,60}?)\s+(is|are|was|were)\s", s, re.I):
        return "STATE"
    if action_lemma in RECORD_LEMMAS:
        return "RECORD"
    if action_lemma in CHECK_LEMMAS:
        return "CHECK"
    if re.match(r"^(the|a|an|this|that|each|every)\b", s, re.I) or \
            (re.match(r"^[a-z]+ing\b", s, re.I) and len(s.split()) <= 2):
        return "REFERENCE"
    if re.match(r"^[a-z]+ing\b", s, re.I):
        return "REFERENCE"
    return "PERFORM"


def build_ir(policy: str, span: str, doc, start: int) -> dict:
    """Deterministic EventMention IR from stanza doc + surface heuristics."""
    act, args = v10.action_signature(span)
    toks = span.split()
    # tokens of the mention inside the doc (case-tolerant start match)
    d_toks = [w for s in doc.sentences for w in s.words
              if start - 1 <= w.start_char < start + len(span) + 1]
    pos = {w.text.lower(): w.upos for w in d_toks}
    deps = {(w.deprel, w.text.lower()) for w in d_toks}
    has_verb = any(p in ("VERB", "AUX") for p in pos.values())
    subj = None
    for w in d_toks:
        if w.deprel in ("nsubj", "nsubj:pass") and w.head:
            subj = w.text
            break
    polarity = "NEG" if any(t.lower() in NEG_WORDS for t in toks) else "POS"
    modality = None
    for t in toks:
        if t.lower() in MODALS:
            modality = t.lower()
            break
    tense = None
    for w in d_toks:
        if w.upos == "VERB" and w.feats:
            m = re.search(r"Tense=([A-Za-z]+)", w.feats or "")
            if m:
                tense = m.group(1).lower()
                break
    voice = "passive" if any(r == "nsubj:pass" for r, _ in deps) or \
        re.search(r"\b(is|are|was|were)\s+\w+ed\b", span, re.I) else "active"
    # temporal context: nearest temporal token in the mention's sentence
    temporal = None
    sent = None
    for s in doc.sentences:
        if s.words and start >= s.words[0].start_char - 2 and \
                start < s.words[-1].end_char + 2:
            sent = s
            break
    if sent:
        for w in sent.words:
            if w.upos in ("ADP", "NOUN") and w.text.lower() in (
                    "before", "after", "during", "upon", "within", "until",
                    "april", "monday", "dawn", "dusk", "hour", "hours",
                    "day", "days", "week", "month", "quarter", "morning",
                    "evening", "night", "noon"):
                temporal = w.text.lower()
                break
    return {
        "mention_id": None,
        "source_span": span,
        "sentence_id": None,
        "predicate": act,
        "predicate_lemma": act,
        "actor": subj,
        "subject": subj,
        "object": next(iter(args), None) if args else None,
        "entity": sorted(args)[:4],
        "arguments": sorted(args),
        "polarity": polarity,
        "modality": modality,
        "tense_aspect": tense,
        "voice": voice,
        "syntactic_form": v10._form_kind(span),
        "event_mode": event_mode_of(span, act),
        "temporal_context": temporal,
        "frontend_provenance": None,
    }


# ------------------------------------------------------------ benchmarks
def normalize_gold(label: str) -> str:
    """EC labels -> 4-way phase labels."""
    if label == "SAME_EVENT":
        return "SAME_EVENT"
    if label in ("RELATED", "RELATED_BUT_DIFFERENT"):
        return "RELATED_BUT_DIFFERENT"
    if label == "DIFFERENT":
        return "DIFFERENT_EVENT"
    return "AMBIGUOUS"


def bench_ec():
    """EC-frozen gold mention pairs -> flat list with span contexts."""
    cases = json.loads((EC / "frozen" / "frozen_cases.json")
                       .read_text(encoding="utf-8"))
    pairs_gold = json.loads((EC / "frozen" / "pairs_gold.json")
                            .read_text(encoding="utf-8"))
    bench = []
    for case in cases:
        cid_ = case["case_id"]
        ms = {m["mid"]: m for m in case["mentions"]}
        for p in pairs_gold.get(cid_, []):
            ma, mb = ms.get(p["a"]), ms.get(p["b"])
            if not ma or not mb:
                continue
            bench.append({
                "case": cid_, "policy": case["policy"],
                "a_mid": p["a"], "b_mid": p["b"],
                "a_span": ma["span"], "b_span": mb["span"],
                "a_start": ma.get("start"), "b_start": mb.get("start"),
                "gold": normalize_gold(p["label"])})
    return bench


def bench_fa(suites=("main", "f2", "f3", "f4")):
    """A-layer mentions (sanitation-only nodes) on F-suites; pair labels
    via gold cid mapping (same cid=SAME; gold-edge=RELATED; else
    DIFFERENT; unlabeled endpoint=AMBIGUOUS)."""
    bench, mentions_by_case = [], {}
    for suite in suites:
        gold = load_gold(suite)
        for cid_, case in gold.items():
            nodes = build_nodes_toggle("LLM_SG", case, skip_unions=True,
                                       skip_consolidation=True,
                                       skip_deontic_attach=True)
            labels = {n["node_id"]: node_label(case, n) for n in nodes}
            gold_edges = {(e["from_cid"], e["to_cid"])
                          for e in case["normative_edges"]}
            mentions_by_case[f"{suite}:{cid_}"] = {
                "policy": case["policy"],
                "mentions": [{"mid": n["node_id"], "span": n["span"],
                              "forms": n.get("member_spans") or [n["span"]],
                              "label": labels[n["node_id"]],
                              "start": n.get("start")}
                             for n in nodes]}
            ms = mentions_by_case[f"{suite}:{cid_}"]["mentions"]
            for i in range(len(ms)):
                for j in range(i + 1, len(ms)):
                    la, lb = ms[i]["label"], ms[j]["label"]
                    if la in (None, "MIXED", "NON_EVENT") or \
                            lb in (None, "MIXED", "NON_EVENT"):
                        lab = "AMBIGUOUS"
                    elif la == lb:
                        lab = "SAME_EVENT"
                    elif (la, lb) in gold_edges or (lb, la) in gold_edges:
                        lab = "RELATED_BUT_DIFFERENT"
                    else:
                        lab = "DIFFERENT_EVENT"
                    bench.append({
                        "case": f"{suite}:{cid_}",
                        "policy": case["policy"],
                        "a_mid": ms[i]["mid"], "b_mid": ms[j]["mid"],
                        "a_span": ms[i]["span"], "b_span": ms[j]["span"],
                        "a_start": ms[i].get("start"),
                        "b_start": ms[j].get("start"),
                        "gold": lab})
    return bench, mentions_by_case


# ------------------------------------------------------------ arms
def arm_a(bench):
    out = []
    for p in bench:
        ov = overlap_coeff(set(content_tokens(p["a_span"])),
                           set(content_tokens(p["b_span"])))
        out.append({"label": "SAME_EVENT" if ov >= 0.5 else
                    "DIFFERENT_EVENT", "score": ov})
    return out


def arm_b(bench, model):
    spans = [p["a_span"] for p in bench] + [p["b_span"] for p in bench]
    V = model.encode(spans, batch_size=64, normalize_embeddings=True,
                     show_progress_bar=False)
    n = len(bench)
    out = []
    for i, p in enumerate(bench):
        sim = float(V[i] @ V[n + i])
        out.append({"score": round(sim, 4)})
    return out


def arm_c(bench, ce):
    inputs = []
    for p in bench:
        q = (f'Do these two policy text mentions refer to the same single '
             f'event? Mention 1: "{p["a_span"]}". Mention 2: '
             f'"{p["b_span"]}".')
        passage = (f'Mention 1: "{p["a_span"]}". Mention 2: '
                   f'"{p["b_span"]}".')
        inputs.append((q, passage))
    scores = ce.predict(inputs, batch_size=64,
                        convert_to_numpy=True).tolist()
    out = []
    for i in range(len(bench)):
        out.append({"score": round(float(scores[i]), 4)})
    return out


def arm_h(bench):
    """v10 deterministic identity as pair classifier (binary)."""
    out = []
    for p in bench:
        comp = v10.compatible_nodes([p["a_span"]], [p["b_span"]])
        out.append({"label": "SAME_EVENT" if comp else "DIFFERENT_EVENT",
                    "score": 1.0 if comp else 0.0})
    return out


def ir_features(bench, nlp, use_forms=False):
    """EventMention IR per unique mention; merged disk cache."""
    cache = OUTD / "_ir_cache.json"
    ir = json.loads(cache.read_text()) if cache.exists() else {}
    docs = {}
    dirty = False
    for p in bench:
        case = p["case"]
        if case not in docs:
            docs[case] = nlp(p["policy"])
        doc = docs[case]
        for key in ("a", "b"):
            mid = f'{case}|{p[key + "_mid"]}'
            if mid in ir:
                continue
            rec = build_ir(p["policy"], p[key + "_span"], doc,
                           p[key + "_start"] or 0)
            rec["mention_id"] = mid
            ir[mid] = rec
            dirty = True
    if dirty:
        cache.write_text(json.dumps(ir))
    return ir


def arm_d_subset(bench, ir, feats, refined=True):
    """UD-signature-style compare over an IR feature subset.

    feats: subset of {predicate, entities, arguments, polarity, modality,
    event_mode, temporal, actor, voice}
    refined semantics (learned from first run, pre-registered before the
    F-A rerun): STATE/REFERENCE are voice-facets of PERFORM (compatible);
    mode conflicts only for CHECK/RECORD vs PERFORM/STATE/REFERENCE;
    modality/temporal conflict only when BOTH sides are non-None and
    different (deontic-vs-bare is not an identity distinction)."""
    out = []
    for p in bench:
        ia = ir[f'{p["case"]}|{p["a_mid"]}']
        ib = ir[f'{p["case"]}|{p["b_mid"]}']
        same = True
        reason = []
        if "predicate" in feats:
            if not (ia["predicate"] and ib["predicate"] and
                    lemma_family_match(ia["predicate"], ib["predicate"])):
                same = False
                reason.append("predicate")
        if same and "entities" in feats:
            if ia["entity"] and ib["entity"] and not (
                    set(ia["entity"]) & set(ib["entity"])):
                same = False
                reason.append("entity")
        if same and "arguments" in feats:
            if ia["arguments"] and ib["arguments"] and not (
                    set(ia["arguments"]) & set(ib["arguments"])):
                same = False
                reason.append("args")
        if same and "polarity" in feats and \
                ia["polarity"] != ib["polarity"]:
            same = False
            reason.append("polarity")
        if same and "modality" in feats:
            ma_, mb_ = ia["modality"], ib["modality"]
            if refined:
                if ma_ and mb_ and ma_ != mb_:
                    same = False
                    reason.append("modality")
            elif ma_ != mb_:
                same = False
                reason.append("modality")
        if same and "event_mode" in feats:
            xa, xb = ia["event_mode"], ib["event_mode"]
            if refined:
                if xa != xb and {xa, xb} & {"CHECK", "RECORD"}:
                    same = False
                    reason.append("mode")
            elif xa != xb:
                same = False
                reason.append("mode")
        if same and "temporal" in feats:
            ta, tb_ = ia["temporal_context"], ib["temporal_context"]
            if refined:
                if ta and tb_ and ta != tb_ and \
                        not lemma_family_match(ta, tb_):
                    same = False
                    reason.append("temporal")
            elif ta != tb_:
                same = False
                reason.append("temporal")
        if same and "actor" in feats and ia["actor"] and ib["actor"] and \
                norm_lemma(ia["actor"]) != norm_lemma(ib["actor"]):
            same = False
            reason.append("actor")
        if same and "voice" in feats and \
                {ia["voice"], ib["voice"]} == {"active", "passive"}:
            reason.append("voice-ok")
        out.append({"label": "SAME_EVENT" if same else "DIFFERENT_EVENT",
                    "reason": ",".join(reason) or "compatible"})
    return out


# ------------------------------------------------------------ metrics
def pair_metrics(bench, preds, thresh=None, score_key="score",
                 positive="SAME_EVENT"):
    """Score arms: thresholded score-arms get labels via dev-calibrated
    threshold; label-arms scored directly. Gold labels normalized 4-way."""
    tp = fp = fn = tn = 0
    dangerous = 0
    conf = Counter()
    for p, pr in zip(bench, preds):
        gold = normalize_gold(p["gold"]) if p["gold"] in (
            "SAME_EVENT", "RELATED", "DIFFERENT", "AMBIGUOUS") \
            else p["gold"]
        if thresh is not None:
            pred = positive if pr.get(score_key, 0) >= thresh \
                else "DIFFERENT_EVENT"
        else:
            pred = pr.get("label", "DIFFERENT_EVENT")
        g4 = gold if gold in LABELS else "AMBIGUOUS"
        conf[(g4, pred)] += 1
        if gold == "SAME_EVENT":
            if pred == "SAME_EVENT":
                tp += 1
            else:
                fn += 1
        else:
            if pred == "SAME_EVENT":
                fp += 1
                if gold == "DIFFERENT_EVENT":
                    dangerous += 1
            else:
                tn += 1
    P = tp / max(1, tp + fp)
    R = tp / max(1, tp + fn)
    F = 2 * P * R / max(1e-9, P + R)
    return {"P": round(P, 3), "R": round(R, 3), "F1": round(F, 3),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "dangerous_merges": dangerous,
            "confusion": {f"{g}->{p}": c for (g, p), c in conf.items()
                          if c}}


def calibrate(bench, preds, score_key="score"):
    """Dev-calibrate threshold maximizing F1 on the SAME class."""
    best = (0.0, -1.0)
    for t in [x / 100 for x in range(20, 96, 5)]:
        m = pair_metrics(bench, preds, thresh=t, score_key=score_key)
        if m["F1"] > best[1]:
            best = (t, m["F1"])
    return best[0]


def main():
    import stanza
    from sentence_transformers import (SentenceTransformer, CrossEncoder)

    print("[bench] building EC benchmark ...")
    ec_bench = bench_ec()
    print(f"[bench] EC pairs: {len(ec_bench)} "
          f"({Counter(p['gold'] for p in ec_bench)})")
    fa_bench, fa_mentions = bench_fa()
    print(f"[bench] F-A pairs: {len(fa_bench)} "
          f"({Counter(p['gold'] for p in fa_bench)})")

    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse",
                          verbose=False, use_gpu=True)
    enc = SentenceTransformer(
        "BAAI/bge-base-en-v1.5", device="cuda",
        cache_folder="/workspace/guardian/hf_cache")
    ce = CrossEncoder("BAAI/bge-reranker-base", device="cuda",
                      max_length=512,
                      cache_folder="/workspace/guardian/hf_cache")

    results = {}
    for bname, bench in (("ec", ec_bench), ("fa", fa_bench)):
        res = {}
        # A
        res["A_lex"] = pair_metrics(bench, arm_a(bench))
        # B
        pb = arm_b(bench, enc)
        tb = calibrate(bench, pb)
        res["B_emb"] = {**pair_metrics(bench, pb, thresh=tb),
                        "threshold": tb}
        # C
        pc = arm_c(bench, ce)
        tc = calibrate(bench, pc)
        res["C_ce"] = {**pair_metrics(bench, pc, thresh=tc),
                       "threshold": tc}
        # H (v10 identity)
        res["H_v10"] = pair_metrics(bench, arm_h(bench))
        # D + IR ablation
        ir = ir_features(bench, nlp)
        ablation_sets = [
            ("D_pred", {"predicate"}),
            ("D_pred+ent", {"predicate", "entities"}),
            ("D_pred+args", {"predicate", "arguments"}),
            ("D_pred+ent+args", {"predicate", "entities", "arguments"}),
            ("D_all", {"predicate", "entities", "arguments", "polarity",
                       "modality", "event_mode", "temporal"}),
            ("D_all+actor", {"predicate", "entities", "arguments",
                             "polarity", "modality", "event_mode",
                             "temporal", "actor"}),
            ("D_no_mode", {"predicate", "entities", "arguments",
                           "polarity", "temporal"}),
            ("D_mode_only", {"predicate", "entities", "arguments",
                             "event_mode"}),
        ]
        for name, feats in ablation_sets:
            res[name] = pair_metrics(bench, arm_d_subset(bench, ir, feats))
        # hybrids of local arms
        ph = arm_h(bench)
        pd_ = arm_d_subset(bench, ir, {"predicate", "entities",
                                       "arguments", "polarity",
                                       "modality", "event_mode",
                                       "temporal"})
        both = [{"label": "SAME_EVENT"
                 if (h["label"] == "SAME_EVENT" and
                     d["label"] == "SAME_EVENT") else "DIFFERENT_EVENT"}
                for h, d in zip(ph, pd_)]
        either = [{"label": "SAME_EVENT"
                   if (h["label"] == "SAME_EVENT" or
                       d["label"] == "SAME_EVENT") else "DIFFERENT_EVENT"}
                  for h, d in zip(ph, pd_)]
        res["I_H_and_D"] = pair_metrics(bench, both)
        res["I_H_or_D"] = pair_metrics(bench, either)
        ce_h = [{"label": "SAME_EVENT"
                 if (c.get("score", 0) >= tc and
                     h["label"] == "SAME_EVENT") else "DIFFERENT_EVENT"}
                for c, h in zip(pc, ph)]
        res["I_CE_and_H"] = pair_metrics(bench, ce_h)
        results[bname] = res
        for k, m in res.items():
            print(f"[{bname}] {k}: F1={m['F1']} P={m['P']} R={m['R']} "
                  f"dangerous={m['dangerous_merges']}")
    (OUTD / "identity_arms.json").write_text(json.dumps(results, indent=1))
    print("saved ->", OUTD / "identity_arms.json")


if __name__ == "__main__":
    main()

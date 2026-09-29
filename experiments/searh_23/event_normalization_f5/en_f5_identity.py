"""EN-3: F5 identity arms — single F5 inference round (directive §4/§5/§7/
§8/§17). Runs on the SEALED F5 suite: no calibration on F5 anywhere.

Arms on the F5 gold-pair bench (219 pairs, span-identified):
  A_lex, B_emb (dev-locked threshold 0.75), C_ce (dev-locked 0.2),
  H_v10, D feature-subset family (same ablation sets as dev), I hybrids,
  F4way (narrow LLM 4-way judge, policy-only, ALL gold pairs).

Modular architecture input (consumed by en_f5_run.py arm 'modular'):
  A-layer sanitized mentions on F5 -> union candidate pairs ->
  H pre-filter + F4way judge -> f5_modular_decisions.json (veto semantics:
  direct SAME_EVENT edges only).

Clustering (Level 2): F4way/veto on gold mentions vs gold clusters
(B3/MUC/CEAF/CoNLL via en_common.cluster_scores) + fa-bench cluster_eval.

Run (server): /workspace/guardian/venv/bin/python en_f5_identity.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
W1 = HERE.parent / "step1_working_v1"
IE = W1.parent / "event_ie_frontends_v1"
sys.path[:0] = [str(W1), str(IE), str(HERE)]

from en_identity import (arm_a, arm_b, arm_c, arm_h, arm_d_subset,  # noqa
                          ir_features, pair_metrics, LABELS)
import en_identity_llm as idl  # noqa: E402  (run_f4way, cand_pairs_of, ...)
from en_common import (node_label, cluster_scores,  # noqa: E402
                       node_clusters_as_sets, gold_clusters_as_sets)
from en_audit import build_nodes_toggle  # noqa: E402
from pl_common import Mistral  # noqa: E402

OUTD = HERE / "outputs" / "identity"
OUTD.mkdir(parents=True, exist_ok=True)

# dev-locked thresholds (identity_arms.json, ec bench, BEFORE any F5 run)
B_THRESH = 0.75
C_THRESH = 0.2

ABLATION_SETS = [
    ("D_pred", {"predicate"}),
    ("D_pred+ent", {"predicate", "entities"}),
    ("D_pred+args", {"predicate", "arguments"}),
    ("D_pred+ent+args", {"predicate", "entities", "arguments"}),
    ("D_all", {"predicate", "entities", "arguments", "polarity",
               "modality", "event_mode", "temporal"}),
    ("D_all+actor", {"predicate", "entities", "arguments", "polarity",
                     "modality", "event_mode", "temporal", "actor"}),
    ("D_no_mode", {"predicate", "entities", "arguments", "polarity",
                   "temporal"}),
    ("D_mode_only", {"predicate", "entities", "arguments", "event_mode"}),
]


def f5_cases() -> list[dict]:
    return json.loads((HERE / "f5_frozen" / "f5_cases.json")
                      .read_text(encoding="utf-8"))["cases"]


def bench_f5() -> list[dict]:
    """F5 gold mention pairs -> flat bench (spans as mention ids)."""
    pairs_gold = json.loads((HERE / "f5_frozen" / "f5_pairs_gold.json")
                            .read_text(encoding="utf-8"))
    bench = []
    for case in f5_cases():
        cid = case["case_id"]
        policy = case["policy"]
        starts = {m[0]: policy.find(m[0]) for m in case["mentions"]}
        for p in pairs_gold.get(cid, []):
            bench.append({
                "case": cid, "policy": policy,
                "a_mid": p["a"], "b_mid": p["b"],
                "a_span": p["a"], "b_span": p["b"],
                "a_start": starts.get(p["a"]),
                "b_start": starts.get(p["b"]),
                "gold": p["label"]})
    return bench


def bench_f5fa():
    """A-layer mentions (sanitation-only nodes) on F5; pair labels via gold
    cid mapping (bench_fa logic, F5 version). Also returns per-case
    mentions for clustering and the A-layer nodes themselves."""
    full = {c["case_id"]: c for c in json.loads(
        (IE / "frozen" / "level_f5_cases.json").read_text(encoding="utf-8"))}
    bench, mentions_by_case, nodes_by_case = [], {}, {}
    for cid_, case in full.items():
        nodes = build_nodes_toggle("LLM_SG", case, skip_unions=True,
                                   skip_consolidation=True,
                                   skip_deontic_attach=True)
        nodes_by_case[cid_] = nodes
        labels = {n["node_id"]: node_label(case, n) for n in nodes}
        gold_edges = {(e["from_cid"], e["to_cid"])
                      for e in case["normative_edges"]}
        mentions_by_case[cid_] = {
            "policy": case["policy"],
            "mentions": [{"mid": n["node_id"], "span": n["span"],
                          "forms": n.get("member_spans") or [n["span"]],
                          "label": labels[n["node_id"]],
                          "start": n.get("start")}
                         for n in nodes]}
        ms = mentions_by_case[cid_]["mentions"]
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
                bench.append({"case": cid_, "policy": case["policy"],
                              "a_mid": ms[i]["mid"], "b_mid": ms[j]["mid"],
                              "a_span": ms[i]["span"],
                              "b_span": ms[j]["span"],
                              "a_start": ms[i].get("start"),
                              "b_start": ms[j].get("start"),
                              "gold": lab})
    return bench, mentions_by_case, nodes_by_case


def gold_clusters_f5() -> dict:
    return json.loads((HERE / "f5_frozen" / "f5_clusters_gold.json")
                      .read_text(encoding="utf-8"))


def cand_pairs_of(bench, enc):
    """Union candidate pairs (locality ∪ lemma ∪ emb-top3), ported from
    en_identity_llm.main.cand_pairs_of (module-level here so it can be
    reused; same logic, enc passed explicitly)."""
    from ec_feats import content_tokens, lemma_family_match

    def sentence_of(policy: str, start: int | None) -> str:
        return idl.sentence_of(policy, start)

    by_case = defaultdict(list)
    for p in bench:
        by_case[p["case"]].append(p)
    keep = set()
    for case, pairs in by_case.items():
        policy = pairs[0]["policy"]
        mids = sorted({p["a_mid"] for p in pairs} | {p["b_mid"]
                                                     for p in pairs})
        span_of, start_of = {}, {}
        for p in pairs:
            span_of[p["a_mid"]] = p["a_span"]
            span_of[p["b_mid"]] = p["b_span"]
            start_of[p["a_mid"]] = p["a_start"]
            start_of[p["b_mid"]] = p["b_start"]
        uniq = [span_of[m] for m in mids]
        V = enc.encode(uniq, batch_size=64, normalize_embeddings=True,
                       show_progress_bar=False)
        vec = {m: V[i] for i, m in enumerate(mids)}
        for i, mi in enumerate(mids):
            top3 = sorted(((float(vec[mi] @ vec[mj]), mj)
                           for j, mj in enumerate(mids) if j != i),
                          reverse=True)[:3]
            for s, mj in top3:
                keep.add((case, mi, mj) if mi < mj else (case, mj, mi))
        for p in pairs:
            # locality + lemma shortcuts
            si = sentence_of(policy, p["a_start"])
            sj = sentence_of(policy, p["b_start"])
            if si == sj and si:
                keep.add((case, p["a_mid"], p["b_mid"]))
            ta = content_tokens(p["a_span"])
            tb = content_tokens(p["b_span"])
            if ta and tb and lemma_family_match(
                    p["a_span"].split()[0].lower(),
                    p["b_span"].split()[0].lower()):
                keep.add((case, p["a_mid"], p["b_mid"]))
    return [p for p in bench
            if (p["case"], p["a_mid"], p["b_mid"]) in keep]


def main() -> None:
    import stanza
    from sentence_transformers import (SentenceTransformer, CrossEncoder)

    client = Mistral(model="ministral-14b-latest", cache_dir=OUTD / "_cache")
    bench = bench_f5()
    (OUTD / "f5_bench.json").write_text(json.dumps(bench, indent=1))
    print(f"[bench] f5 gold pairs: {len(bench)} "
          f"({Counter(p['gold'] for p in bench)})", flush=True)

    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse",
                          verbose=False, use_gpu=True)
    enc = SentenceTransformer("BAAI/bge-base-en-v1.5", device="cuda",
                              cache_folder="/workspace/guardian/hf_cache")
    ce = CrossEncoder("BAAI/bge-reranker-base", device="cuda",
                      max_length=512,
                      cache_folder="/workspace/guardian/hf_cache")

    # ---------------- deterministic arms on the gold-pair bench
    res: dict = {}
    res["A_lex"] = pair_metrics(bench, arm_a(bench))
    pb = arm_b(bench, enc)
    res["B_emb"] = {**pair_metrics(bench, pb, thresh=B_THRESH),
                    "threshold": B_THRESH, "note": "dev-locked"}
    pc = arm_c(bench, ce)
    res["C_ce"] = {**pair_metrics(bench, pc, thresh=C_THRESH),
                   "threshold": C_THRESH, "note": "dev-locked"}
    res["H_v10"] = pair_metrics(bench, arm_h(bench))
    ir = ir_features(bench, nlp)
    for name, feats in ABLATION_SETS:
        res[name] = pair_metrics(bench, arm_d_subset(bench, ir, feats))
    ph = arm_h(bench)
    pd_ = arm_d_subset(bench, ir, {"predicate", "entities", "arguments",
                                   "polarity", "modality", "event_mode",
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
    for k, m in res.items():
        print(f"[f5] {k}: F1={m['F1']} P={m['P']} R={m['R']} "
              f"dangerous={m['dangerous_merges']}", flush=True)
    (OUTD / "f5_identity_arms.json").write_text(json.dumps(res, indent=1))

    # ---------------- F4way on ALL gold pairs
    f4 = idl.run_f4way(bench, client)
    (OUTD / "f4way_f5.json").write_text(json.dumps(f4, indent=1))
    res["F4way"] = pair_metrics(
        bench, [{"label": d["label"]} for d in f4])
    res["F4way"]["n_pairs"] = len(f4)
    res["F4way"]["label_dist"] = dict(Counter(d["label"] for d in f4))
    print("[f5] F4way:", res["F4way"], flush=True)
    (OUTD / "f5_identity_arms.json").write_text(json.dumps(res, indent=1))

    # ---------------- candidate generation analysis (§8)
    cand = idl.candidate_analysis(bench, enc=enc)
    (OUTD / "f5_candidate_analysis.json").write_text(json.dumps(cand,
                                                                 indent=1))
    print("[f5] candidate generation:", cand, flush=True)

    # ---------------- A-layer bench + modular decisions
    fa_bench, fa_mentions, _nodes = bench_f5fa()
    print(f"[bench] f5 A-layer pairs: {len(fa_bench)} "
          f"({Counter(p['gold'] for p in fa_bench)})", flush=True)
    (OUTD / "f5fa_bench.json").write_text(json.dumps(fa_bench, indent=1))
    fa_cand = cand_pairs_of(fa_bench, enc)
    print(f"[bench] f5 A-layer candidate pairs: {len(fa_cand)}",
          flush=True)

    # H pre-filter + F4way on candidate pairs -> modular decisions
    ph_fa = dict(((p["case"], p["a_mid"], p["b_mid"]), d)
                 for p, d in zip(fa_bench, arm_h(fa_bench)))
    f4_fa = idl.run_f4way(fa_bench, client, cand_pairs=fa_cand)
    (OUTD / "f4way_f5fa.json").write_text(json.dumps(f4_fa, indent=1))
    by_key = {(d["case"], d["a"], d["b"]): d for d in f4_fa}
    decisions: dict[str, list] = defaultdict(list)
    fa_res = {}
    sub_bench = [p for p in fa_cand]
    sub_pred = [{"label": by_key[(p["case"], p["a_mid"], p["b_mid"])]
                 ["label"]}
                for p in sub_bench
                if (p["case"], p["a_mid"], p["b_mid"]) in by_key]
    sub_bench = [p for p in sub_bench
                 if (p["case"], p["a_mid"], p["b_mid"]) in by_key]
    fa_res["F4way_fa"] = pair_metrics(sub_bench, sub_pred)
    fa_res["F4way_fa"]["n_pairs"] = len(sub_bench)
    print("[f5] F4way_fa:", fa_res["F4way_fa"], flush=True)

    hybrid_pred = []
    for p in fa_bench:
        k = (p["case"], p["a_mid"], p["b_mid"])
        if ph_fa.get(k, {}).get("label") == "SAME_EVENT":
            lab = "SAME_EVENT"
        else:
            d = by_key.get(k)
            lab = d["label"] if d else "AMBIGUOUS"
        hybrid_pred.append({"label": lab})
        decisions[p["case"]].append({"a": p["a_span"],
                                     "b": p["b_span"], "label": lab})
    fa_res["I_HF_fa"] = pair_metrics(fa_bench, hybrid_pred)
    print("[f5] I_HF_fa:", fa_res["I_HF_fa"], flush=True)
    (OUTD / "f5_modular_decisions.json").write_text(
        json.dumps(decisions, indent=1))
    print(f"[modular] decisions for {len(decisions)} cases -> "
          f"f5_modular_decisions.json", flush=True)

    # ---------------- clustering (Level 2, §17)
    gold_cl = gold_clusters_f5()
    clustering = {}

    def macro_cluster_scores(pred_by_case, gold_by_case):
        """Per-case cluster_scores, macro-averaged (B3/MUC/CEAF are
        per-document metrics)."""
        per_case = {}
        for case in sorted(gold_by_case):
            preds = pred_by_case.get(case) or []
            golds = [set(v) for v in (gold_by_case.get(case) or
                                      {}).values()]
            per_case[case] = cluster_scores([set(c) for c in preds],
                                            golds)
        agg = {"conll_f": round(sum(v["conll_f"] for v in
                                    per_case.values()) /
                                max(1, len(per_case)), 4)}
        for k in ("b3", "muc", "ceaf_e"):
            agg[k] = [round(sum(v[k][i] for v in per_case.values()) /
                            max(1, len(per_case)), 4) for i in range(3)]
        agg["n_cases"] = len(per_case)
        return agg

    # (a) F4way veto clustering over GOLD mentions (bench pairs, span ids)
    for method in ("veto", "cc", "cc_or_related"):
        cl = idl.cluster_mentions(bench, f4, method=method)
        clustering[f"gold_mentions_F4way_{method}"] = \
            macro_cluster_scores(cl, gold_cl)
        print(f"[cluster:gold:{method}]",
              clustering[f"gold_mentions_F4way_{method}"], flush=True)
    # (b) modular (H-and-F) veto clustering over A-layer mentions
    labeller = idl.gold_labeller_fa(fa_mentions)
    for method in ("veto", "cc"):
        cl = idl.cluster_mentions(fa_bench, hybrid_pred, method=method)
        ev = idl.cluster_eval(fa_bench, cl, labeller)
        clustering[f"alayer_HF_{method}"] = ev
        print(f"[cluster:alayer:{method}]", ev["aggregate"], flush=True)
    (OUTD / "f5_clustering.json").write_text(json.dumps(clustering, indent=1))

    # ---------------- summary
    fa_res["H_fa"] = pair_metrics(fa_bench, arm_h(fa_bench))
    summary = {"gold_pair_arms": res, "fa_arms": fa_res,
               "clustering": clustering}
    (OUTD / "f5_identity_summary.json").write_text(json.dumps(summary,
                                                              indent=1))
    print("saved ->", OUTD / "f5_identity_summary.json", flush=True)


if __name__ == "__main__":
    main()

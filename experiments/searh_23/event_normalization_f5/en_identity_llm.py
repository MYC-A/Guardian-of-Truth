"""LLM identity arms + candidate generation analysis + tool ablation.

1. Candidate generation (directive §8): locality / lemma-family /
   embedding-top3 / union — pair candidate recall@k, reduction,
   hard-negative density on both dev benchmarks.
2. F4way: narrow LLM pair judge with explicit AMBIGUOUS outcome,
   run ONLY on candidate pairs (narrow task, §27).
3. Tool ablation (§26): judge × {policy-only, +tool names,
   +tool descriptions} on the fa benchmark subsample.
4. Hybrid I_HF: H_v10 pre-filter + F4way judge + AMBIGUOUS=do-not-merge.
5. Clustering comparison on the fa benchmark (modular architecture):
   cc / veto / avg-link / complete-link over arm decisions; node metrics
   vs gold clusters; comparison vs v10 monolithic (A+B).

Run (server): source secrets; python en_identity_llm.py
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
W1 = HERE.parent / "step1_working_v1"
EC = HERE.parent / "event_canon_v1"
PL = W1.parent / "policy_licensing_v1"
IE = W1.parent / "event_ie_frontends_v1"
sys.path.insert(0, str(W1))
sys.path.insert(0, str(PL))
sys.path.insert(0, str(EC))
sys.path.insert(0, str(IE))

from pl_common import Mistral  # noqa: E402
from ec_feats import content_tokens, lemma_family_match  # noqa: E402
import w1_pipe3 as v10  # noqa: E402
from en_identity import (bench_ec, bench_fa, pair_metrics, arm_h,  # noqa
                         LABELS)

OUTD = HERE / "outputs" / "identity"
OUTD.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------ candidate generation
def sentence_of(policy: str, start: int | None) -> str:
    if start is None:
        return ""
    s0, s1 = v10.sent_span(policy, start)
    return policy[s0:s1].strip()


def candidate_analysis(bench, mentions_by_case=None, enc=None):
    """Recall/reduction/density of candidate generators (§8).

    Generators: locality (same/adjacent sentence), lemma-family
    (predicates related), emb-top3 (bge cosine top-3 partners), union.
    Pair-level gold SAME recall is the critical number."""
    from sentence_transformers import SentenceTransformer
    if enc is None:
        enc = SentenceTransformer("BAAI/bge-base-en-v1.5", device="cuda",
                                  cache_folder="/workspace/guardian/hf_cache")
    by_case = defaultdict(list)
    for p in bench:
        by_case[p["case"]].append(p)
    stats = {g: {"cand": 0, "same_found": 0, "diff_cand": 0}
             for g in ("locality", "lemma", "emb3", "union")}
    gold_same_total = 0
    emb_cache = {}
    for case, pairs in by_case.items():
        policy = pairs[0]["policy"]
        mids = sorted({p["a_mid"] for p in pairs} | {p["b_mid"]
                                                     for p in pairs})
        span_of = {}
        for p in pairs:
            span_of[p["a_mid"]] = p["a_span"]
            span_of[p["b_mid"]] = p["b_span"]
            span_of[(p["case"], p["a_mid"])] = p["a_span"]
            span_of[(p["case"], p["b_mid"])] = p["b_span"]
        start_of = {}
        for p in pairs:
            start_of[p["a_mid"]] = p["a_start"]
            start_of[p["b_mid"]] = p["b_start"]
        # embed spans
        uniq = [span_of[m] for m in mids]
        V = enc.encode(uniq, batch_size=64, normalize_embeddings=True,
                       show_progress_bar=False)
        vec = {m: V[i] for i, m in enumerate(mids)}
        sents = {m: sentence_of(policy, start_of.get(m))
                 for m in mids}
        gold_same = {(p["a_mid"], p["b_mid"]) for p in pairs
                     if p["gold"] == "SAME_EVENT"}
        gold_same_total += len(gold_same)
        gen = {g: set() for g in stats}
        for i, mi in enumerate(mids):
            for mj in mids[i + 1:]:
                # locality: same or adjacent sentence
                si, sj = sents[mi], sents[mj]
                if si and sj and (si == sj or abs(len(si) - len(sj)) >= 0
                                  and (si in sj or sj in si or
                                       _adjacent(policy, start_of.get(mi),
                                                 start_of.get(mj)))):
                    gen["locality"].add((mi, mj))
                # lemma family on first content token
                ti = content_tokens(span_of[mi])
                tj = content_tokens(span_of[mj])
                if ti and tj and (
                        lemma_family_match(sorted(ti)[0], sorted(tj)[0])
                        or lemma_family_match(span_of[mi].split()[0].lower(),
                                              span_of[mj].split()[0].lower())):
                    gen["lemma"].add((mi, mj))
        # emb top-3 per mention
        for i, mi in enumerate(mids):
            sims = sorted(((float(vec[mi] @ vec[mj]), mj)
                           for j, mj in enumerate(mids) if j != i),
                          reverse=True)[:3]
            for s, mj in sims:
                gen["emb3"].add((mi, mj) if mi < mj else (mj, mi))
        gen["union"] = gen["locality"] | gen["lemma"] | gen["emb3"]
        for g, cands in gen.items():
            stats[g]["cand"] += len(cands)
            stats[g]["same_found"] += len(
                {c for c in cands if c in gold_same or
                 (c[1], c[0]) in gold_same})
            stats[g]["diff_cand"] += len(
                {c for c in cands if c not in gold_same and
                 (c[1], c[0]) not in gold_same})
    out = {}
    total_pairs = len(bench)
    for g, s in stats.items():
        out[g] = {
            "candidate_pairs": s["cand"],
            "reduction": round(1 - s["cand"] / max(1, total_pairs), 3),
            "same_recall": round(s["same_found"] /
                                 max(1, gold_same_total), 4),
            "hard_negative_density": round(
                s["diff_cand"] / max(1, s["cand"]), 3)}
    return out


def _adjacent(policy: str, s1: int | None, s2: int | None) -> bool:
    if s1 is None or s2 is None:
        return False
    a, b = v10.sent_span(policy, s1), v10.sent_span(policy, s2)
    return abs(a[0] - b[0]) < 400 and a != b


# ------------------------------------------------------------ F4way judge
F4_SYSTEM = """You decide whether two event mentions from the same policy text refer to the SAME single event occurrence, are merely related but DISTINCT events, are clearly DIFFERENT events, or the text is insufficient to decide (AMBIGUOUS).

SAME single event: the two spans denote one and the same prescribed or reported occurrence - e.g. an imperative and a later passive or nominal reference to it ('Weigh each batch' / 'after the batch is weighed'), or an anaphoric reference ('This verification', 'the inspection' pointing at 'Inspect the filter').
RELATED but DISTINCT events: an action vs a check or observation of that action ('make the payment' / 'verify the payment was made'); an action vs its result state; an action vs the recording of that action ('the cleaning' / 'the cleaning is logged'); same predicate on different entities ('Feed the otters' / 'Feed the red pandas'); different occurrence of the same action ('weigh the batch' / 'weigh the batch again').
DIFFERENT events: different predicates or unrelated actions.
AMBIGUOUS: the text does not give enough evidence to decide (use this instead of guessing).
Judge ONLY from the given text; do not use world knowledge to merge similar-sounding events. Semantic similarity is NOT same event. Same predicate is NOT automatically same event.
Answer with JSON only: {"label": "SAME_EVENT"|"RELATED_BUT_DIFFERENT"|"DIFFERENT_EVENT"|"AMBIGUOUS", "reason": "<one short sentence citing the decisive text>"}."""


def f4_user(policy: str, a_span: str, b_span: str, ctx_a: str, ctx_b: str,
            tools_block: str = "") -> str:
    return (f"POLICY:\n{policy}\n\n{tools_block}"
            f'MENTION A: "{a_span}"\n'
            f'Context of A: "{ctx_a}"\n\n'
            f'MENTION B: "{b_span}"\n'
            f'Context of B: "{ctx_b}"\n\n'
            "Do A and B refer to the same single event occurrence? "
            "Answer with JSON only.")


def run_f4way(bench, client, cand_pairs=None, tools_mode="none",
              case_tools=None, limit=None):
    """F4way judge over benchmark pairs (optionally only candidate pairs;
    tools_mode: none | names | descriptions)."""
    out = []
    keyset = set()
    if cand_pairs is not None:
        keyset = {(p["case"], p["a_mid"], p["b_mid"]) for p in cand_pairs}
    n = 0
    for p in bench:
        if keyset and (p["case"], p["a_mid"], p["b_mid"]) not in keyset:
            continue
        if limit and n >= limit:
            break
        policy = p["policy"]
        ctx_a = sentence_of(policy, p["a_start"])
        ctx_b = sentence_of(policy, p["b_start"])
        tools_block = ""
        if tools_mode != "none" and case_tools:
            tl = case_tools.get(p["case"], [])
            if tools_mode == "names":
                tools_block = ("TOOLS available in this workplace:\n"
                               + "\n".join(f"- {t['name']}" for t in tl)
                               + "\n\n")
            else:
                tools_block = ("TOOLS available in this workplace:\n"
                               + "\n".join(
                                   f"- {t['name']}: {t['description']}"
                                   for t in tl) + "\n\n")
        user = f4_user(policy, p["a_span"], p["b_span"], ctx_a, ctx_b,
                       tools_block)
        rec = client.ask(F4_SYSTEM, user, max_tokens=200)
        ans, _err = Mistral.parse_json(rec["raw"])
        label = (ans or {}).get("label", "AMBIGUOUS")
        if label not in LABELS:
            label = "AMBIGUOUS"
        out.append({"case": p["case"], "a": p["a_mid"], "b": p["b_mid"],
                    "gold": p["gold"], "label": label,
                    "reason": (ans or {}).get("reason", ""),
                    "cached": rec.get("cached", False)})
        n += 1
        if n % 50 == 0:
            print(f"  [f4:{tools_mode}] {n} pairs judged", flush=True)
    return out


# ---------------------------------------------------------------- clustering
def cluster_mentions(bench, decisions, method="veto"):
    """Cluster mentions per case from pair decisions.

    decisions: list aligned with bench subset of (label) — SAME_EVENT
    edges merge; others don't. veto = union-find on SAME only (no
    transitive closure through uncertain pairs is prevented by requiring
    direct SAME edges). cc = full transitive closure. avg/complete-link
    need scores - not used here (binary decisions)."""
    by_case = defaultdict(list)
    for p, d in zip(bench, decisions):
        by_case[p["case"]].append((p, d))
    clusters_all = {}
    for case, items in by_case.items():
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[ry] = rx

        for p, d in items:
            find(p["a_mid"])
            find(p["b_mid"])
            if method in ("veto", "cc") and d["label"] == "SAME_EVENT":
                union(p["a_mid"], p["b_mid"])
            elif method == "cc_or_related" and d["label"] in (
                    "SAME_EVENT", "RELATED_BUT_DIFFERENT"):
                union(p["a_mid"], p["b_mid"])
        groups = defaultdict(list)
        for m in list(parent):
            groups[find(m)].append(m)
        clusters_all[case] = list(groups.values())
    return clusters_all


def cluster_eval(bench, clusters_all, gold_labeller):
    """Node metrics for predicted clusters vs gold cid clusters."""
    per_case = {}
    agg = Counter()
    for case, clusters in clusters_all.items():
        # gold clusters over the same mention ids
        gold_map = gold_labeller(case)  # mid -> gold cid
        gold_clusters = defaultdict(list)
        for m, g in gold_map.items():
            gold_clusters[g].append(m)
        # metrics: coverage / purity / false merges / false splits
        n_pred = len(clusters)
        false_merge = sum(
            1 for c in clusters
            if len({gold_map.get(m) for m in c}) > 1)
        purity = sum(
            max(Counter(gold_map.get(m) for m in c).values()) /
            len(c) for c in clusters) / max(1, n_pred)
        cov = len({gold_map.get(m) for c in clusters for m in c
                   if gold_map.get(m)})
        false_split = sum(
            1 for g, ms in gold_clusters.items()
            if sum(1 for c in clusters if any(m in c for m in ms)) > 1)
        per_case[case] = {"n_clusters": n_pred, "false_merge": false_merge,
                          "purity": round(purity, 3), "coverage": cov,
                          "false_split": false_split}
        for k in ("n_clusters", "false_merge", "coverage", "false_split"):
            agg[k] += per_case[case][k]
        agg["purity"] += purity
    agg["purity"] = round(agg["purity"] / max(1, len(clusters_all)), 4)
    return {"aggregate": dict(agg), "per_case": per_case}


def gold_labeller_fa(mentions_by_case):
    def f(case):
        return {m["mid"]: m["label"] for m in
                mentions_by_case[case]["mentions"]
                if m["label"] not in (None, "MIXED", "NON_EVENT")}
    return f


# ---------------------------------------------------------------- main
def main():
    client = Mistral(model="ministral-14b-latest",
                     cache_dir=OUTD / "_cache")
    ec_bench = bench_ec()
    fa_bench, fa_mentions = bench_fa()
    print(f"[bench] ec={len(ec_bench)} fa={len(fa_bench)}")

    # 1. candidate generation analysis (uses GPU encoder)
    from sentence_transformers import SentenceTransformer
    enc = SentenceTransformer("BAAI/bge-base-en-v1.5", device="cuda",
                              cache_folder="/workspace/guardian/hf_cache")
    cand = {}
    for bname, bench in (("ec", ec_bench), ("fa", fa_bench)):
        cand[bname] = candidate_analysis(bench, enc=enc)
        print(f"[cand:{bname}] {cand[bname]}")
    (OUTD / "candidate_generation.json").write_text(
        json.dumps(cand, indent=1))

    # candidate pair sets for LLM arms (union generator)
    def cand_pairs_of(bench):
        by_case = defaultdict(list)
        for p in bench:
            by_case[p["case"]].append(p)
        keep = set()
        for case, pairs in by_case.items():
            policy = pairs[0]["policy"]
            mids = sorted({p["a_mid"] for p in pairs} |
                          {p["b_mid"] for p in pairs})
            span_of, start_of = {}, {}
            for p in pairs:
                span_of[p["a_mid"]] = p["a_span"]
                span_of[p["b_mid"]] = p["b_span"]
                start_of[p["a_mid"]] = p["a_start"]
                start_of[p["b_mid"]] = p["b_start"]
            V = enc.encode([span_of[m] for m in mids], batch_size=64,
                           normalize_embeddings=True, show_progress_bar=False)
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

    ec_cand = cand_pairs_of(ec_bench)
    fa_cand = cand_pairs_of(fa_bench)
    print(f"[cand] ec candidates={len(ec_cand)} "
          f"fa candidates={len(fa_cand)}")

    # 2. F4way on candidate pairs (policy only)
    results = {}
    f4_ec = run_f4way(ec_bench, client, cand_pairs=ec_cand)
    f4_fa = run_f4way(fa_bench, client, cand_pairs=fa_cand)
    (OUTD / "f4way_ec.json").write_text(json.dumps(f4_ec, indent=1))
    (OUTD / "f4way_fa.json").write_text(json.dumps(f4_fa, indent=1))

    def f4_metrics(f4_out, bench):
        # align: only judged pairs
        by_key = {(d["case"], d["a"], d["b"]): d for d in f4_out}
        sub_bench, sub_pred = [], []
        for p in bench:
            d = by_key.get((p["case"], p["a_mid"], p["b_mid"]))
            if d:
                sub_bench.append(p)
                sub_pred.append({"label": d["label"]})
        m = pair_metrics(sub_bench, sub_pred)
        m["n_pairs"] = len(sub_bench)
        m["label_dist"] = dict(Counter(d["label"] for d in f4_out))
        m["cached"] = sum(1 for d in f4_out if d.get("cached"))
        return m

    results["F4way_ec"] = f4_metrics(f4_ec, ec_bench)
    results["F4way_fa"] = f4_metrics(f4_fa, fa_bench)
    print("[F4way_ec]", results["F4way_ec"])
    print("[F4way_fa]", results["F4way_fa"])

    # 3. tool ablation on fa subsample (first 150 candidate pairs with
    # tools available in the case)
    case_tools = {}
    for suite in ("main", "f2", "f3", "f4"):
        from en_common import load_gold
        for cid_, case in load_gold(suite).items():
            case_tools[f"{suite}:{cid_}"] = case["tools"]
    fa_tools = [p for p in fa_cand if case_tools.get(p["case"])]
    sub = fa_tools[:150]
    for mode in ("names", "descriptions"):
        f4t = run_f4way(sub, client, cand_pairs=sub, tools_mode=mode,
                        case_tools=case_tools)
        by_key = {(d["case"], d["a"], d["b"]): d for d in f4t}
        sub_bench = [p for p in sub
                     if (p["case"], p["a_mid"], p["b_mid"]) in by_key]
        sub_pred = [{"label": by_key[(p["case"], p["a_mid"],
                                      p["b_mid"])]["label"]}
                    for p in sub_bench]
        results[f"F4way_tool_{mode}"] = pair_metrics(sub_bench, sub_pred)
        results[f"F4way_tool_{mode}"]["n_pairs"] = len(sub_bench)
        print(f"[F4way_tool_{mode}]", results[f"F4way_tool_{mode}"])
    (OUTD / "identity_llm.json").write_text(json.dumps(results, indent=1))

    # 4. hybrid H + F on fa: H says SAME -> SAME; else F decides;
    #    F AMBIGUOUS -> no merge
    ph = dict(((p["case"], p["a_mid"], p["b_mid"]), d)
              for p, d in zip(fa_bench, arm_h(fa_bench)))
    by_key = {(d["case"], d["a"], d["b"]): d for d in f4_fa}
    hybrid = []
    for p in fa_bench:
        k = (p["case"], p["a_mid"], p["b_mid"])
        if ph.get(k, {}).get("label") == "SAME_EVENT":
            hybrid.append({"label": "SAME_EVENT"})
        else:
            d = by_key.get(k)
            hybrid.append({"label": d["label"] if d else "AMBIGUOUS"})
    results["I_HF_fa"] = pair_metrics(fa_bench, hybrid)
    print("[I_HF_fa]", results["I_HF_fa"])

    # 5. clustering comparison (modular architecture on fa mentions)
    labeller = gold_labeller_fa(fa_mentions)
    for method in ("veto", "cc", "cc_or_related"):
        cl = cluster_mentions(fa_bench, hybrid, method=method)
        ev = cluster_eval(fa_bench, cl, labeller)
        results[f"cluster_{method}_HF_fa"] = ev
        print(f"[cluster:{method}]", ev["aggregate"])
    # H-only clustering for comparison
    ph_list = [ph.get((p["case"], p["a_mid"], p["b_mid"]),
                      {"label": "DIFFERENT_EVENT"}) for p in fa_bench]
    for method in ("veto", "cc"):
        cl = cluster_mentions(fa_bench, ph_list, method=method)
        ev = cluster_eval(fa_bench, cl, labeller)
        results[f"cluster_{method}_H_fa"] = ev
        print(f"[cluster:H:{method}]", ev["aggregate"])
    (OUTD / "identity_llm.json").write_text(json.dumps(results, indent=1))
    print("saved ->", OUTD / "identity_llm.json")


if __name__ == "__main__":
    main()

"""EN-5: External ECR baselines on the F5 sealed suite (directive §6).

Actually-run baselines (identical protocol, zero-shot transfer):
  1. LingMess (Otmazgin et al., NAACL 2022) - linguistically-informed
     multi-expert coref scorer, longformer-large, trained on OntoNotes
     ENTITY coreference. Local weights ext_models/lingmess (2.36G).
     transformers-5 compat via attn_implementation=eager + tied-weight
     shims.
  2. coreferee (Böttcher, 2021; model 1.5.0) - spaCy coreference pipe,
     trained on OntoNotes/GAP/NW MaleWiki. pip + model from GitHub.

Protocol (deterministic, documented):
  - predict coreference clusters on each F5 policy text;
  - map a gold EVENT mention to a predicted cluster iff a cluster span
    equals the mention span (case/space-normalized);
  - pair decision: SAME_EVENT iff both mentions map into the SAME
    cluster, else DIFFERENT_EVENT (no abstention);
  - pair_metrics over the 219 frozen gold pairs; cluster-level
    B3/MUC/CEAF/CoNLL over gold event mentions (unclustered -> singleton);
  - mention coverage: how many gold event spans appear among predicted
    cluster spans at all.

Documented blockers (checked this session):
  - fast-coref / CRAC 'On Generalization' (Toledo et al. 2021): direct
    file URLs return Google 404 pages (ext_models/coref/model.pth IS a
    404 HTML page); gdown folder listing retrieves the top-level folder
    structure only, nested model dirs download 0 files.
  - biu-nlp/fcoref (fastcoref pip model card): HF returns 401 'Invalid
    username or password' for anonymous access (gated org) - same for
    biu-nlp/lingmess-large API (our local LingMess weights were obtained
    earlier and verified working).
  - SECURE (taolusi/SECURE, ACL'24): no runnable public checkpoint found
    accessible from this network.
  - MAVEN-ERE trigger tagger: no standalone downloadable trigger model.

Run (server): /workspace/guardian/venv/bin/python en_f5_external.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from en_f5_identity import bench_f5, gold_clusters_f5  # noqa: E402
from en_identity import pair_metrics  # noqa: E402
from en_common import cluster_scores  # noqa: E402

OUTD = HERE / "outputs" / "external"
OUTD.mkdir(parents=True, exist_ok=True)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def score_clusters_mapping(bench, mapping, gold_cl, name):
    """mapping: {case: {span_norm: cluster_id}} for gold event mentions.

    Returns pair metrics + cluster-level metrics (PER-CASE cluster_scores,
    macro-averaged - B3/MUC/CEAF are per-document metrics). Unmapped
    mentions are singletons (never co-clustered)."""
    preds = []
    for p in bench:
        cm = mapping.get(p["case"], {})
        ca = cm.get(_norm(p["a_span"]))
        cb = cm.get(_norm(p["b_span"]))
        same = ca is not None and ca == cb
        preds.append({"label": "SAME_EVENT" if same else
                      "DIFFERENT_EVENT"})
    pm = pair_metrics(bench, preds)
    # cluster-level per case: gold event mentions mapped to cluster ids
    per_case = {}
    cases = sorted({p["case"] for p in bench})
    for case in cases:
        pred_by_cid = defaultdict(set)
        gold_event_spans = set()
        for spans in (gold_cl.get(case) or {}).values():
            gold_event_spans |= set(spans)
        cm = mapping.get(case, {})
        for span in gold_event_spans:
            pred_by_cid[cm.get(_norm(span), f"__sing_{span}")].add(span)
        gold_sets = [set(v) for v in (gold_cl.get(case) or {}).values()]
        per_case[case] = cluster_scores(list(pred_by_cid.values()),
                                        gold_sets)
    agg = {}
    for k in ("conll_f",):
        agg[k] = round(sum(v[k] for v in per_case.values()) /
                       max(1, len(per_case)), 4)
    for k in ("b3", "muc", "ceaf_e"):
        agg[k] = [round(sum(v[k][i] for v in per_case.values()) /
                        max(1, len(per_case)), 4) for i in range(3)]
    agg["n_cases"] = len(per_case)
    return {"pair": pm, "cluster": agg, "cluster_per_case": per_case}


def run_lingmess(bench, gold_cl):
    from transformers import PreTrainedModel
    _orig = PreTrainedModel.from_pretrained

    def _patched(cls, *a, **k):
        k.setdefault("attn_implementation", "eager")
        return _orig.__func__(cls, *a, **k) if hasattr(_orig, "__func__") \
            else _orig(cls, *a, **k)

    PreTrainedModel.from_pretrained = classmethod(_patched)
    from fastcoref import LingMessCoref
    from fastcoref import modeling as fm
    for _cls in (getattr(fm, "LingMessModel", None),
                 getattr(fm, "LingMessForCoref", None)):
        if _cls is not None and not hasattr(_cls, "all_tied_weights_keys"):
            _cls.all_tied_weights_keys = {}
            _cls._tied_weights_keys = []
    m = LingMessCoref(device="cuda:0",
                      model_name_or_path="/workspace/guardian/ext_models/"
                                         "lingmess",
                      nlp="en_core_web_sm")
    policies = {}
    for p in bench:
        policies.setdefault(p["case"], p["policy"])
    mapping: dict[str, dict] = {}
    n_pred_clusters = 0
    n_pred_spans = 0
    for case, policy in policies.items():
        preds = m.predict(texts=[policy])
        clusters = preds[0].get_clusters() or []
        cm: dict[str, int] = {}
        for ci, cl in enumerate(clusters):
            n_pred_clusters += 1
            for sp in cl:
                n_pred_spans += 1
                key = _norm(sp)
                if key not in cm:
                    cm[key] = ci
        mapping[case] = cm
        print(f"[lingmess] {case}: {len(clusters)} clusters", flush=True)
    total_gold = sum(len({s for v in (gold_cl.get(c) or {}).values()
                          for s in v}) for c in policies)
    found = sum(1 for case in policies for spans in
                (gold_cl.get(case) or {}).values()
                for s in spans if _norm(s) in mapping.get(case, {}))
    coverage = {"gold_event_mentions": total_gold,
                "found_in_clusters": found,
                "n_predicted_clusters": n_pred_clusters,
                "n_predicted_spans": n_pred_spans}
    res = score_clusters_mapping(bench, mapping, gold_cl, "lingmess")
    res["coverage"] = coverage
    res["model"] = "LingMess (longformer-large, OntoNotes entity coref,"\
                   " local weights)"
    return res, mapping


def run_coreferee(bench, gold_cl):
    import spacy
    nlp = spacy.load("en_core_web_sm", exclude=["ner"])
    nlp.add_pipe("coreferee")
    policies = {}
    for p in bench:
        policies.setdefault(p["case"], p["policy"])
    mapping: dict[str, dict] = {}
    stats = {"n_chains": 0, "n_chain_mentions": 0}
    for case, policy in policies.items():
        doc = nlp(policy)
        cm: dict[str, int] = {}
        chunks = {id(c): c for c in doc.noun_chunks}
        tok2chunk = {}
        for c in doc.noun_chunks:
            for t in c:
                tok2chunk[t.i] = c
        for ci, chain in enumerate(doc._.coref_chains):
            stats["n_chains"] += 1
            for token_idx in chain:
                try:
                    tok = doc[token_idx]
                except Exception:
                    continue
                c = tok2chunk.get(tok.i)
                text = c.text if c is not None else tok.text
                stats["n_chain_mentions"] += 1
                key = _norm(text)
                if key not in cm:
                    cm[key] = ci
        mapping[case] = cm
        print(f"[coreferee] {case}: {len(doc._.coref_chains)} chains",
              flush=True)
    total_gold = sum(len({s for v in (gold_cl.get(c) or {}).values()
                          for s in v}) for c in policies)
    found = sum(1 for case in policies for spans in
                (gold_cl.get(case) or {}).values()
                for s in spans if _norm(s) in mapping.get(case, {}))
    res = score_clusters_mapping(bench, mapping, gold_cl, "coreferee")
    res["coverage"] = {"gold_event_mentions": total_gold,
                       "found_in_clusters": found, **stats}
    res["model"] = "coreferee 1.5.0 en (spaCy pipe, OntoNotes+GAP+wiki)"
    return res, mapping


def main() -> None:
    bench = bench_f5()
    gold_cl = gold_clusters_f5()
    out = {}
    print(f"[ext] bench: {len(bench)} pairs; "
          f"{len(gold_cl)} cases with gold clusters", flush=True)
    res_lm, map_lm = run_lingmess(bench, gold_cl)
    out["lingmess"] = res_lm
    print("[ext:lingmess]", json.dumps(res_lm["pair"]),
          json.dumps(res_lm["cluster"]), flush=True)
    res_cf, map_cf = run_coreferee(bench, gold_cl)
    out["coreferee"] = res_cf
    print("[ext:coreferee]", json.dumps(res_cf["pair"]),
          json.dumps(res_cf["cluster"]), flush=True)
    (OUTD / "f5_external.json").write_text(json.dumps(out, indent=1))
    (OUTD / "f5_external_mappings.json").write_text(json.dumps(
        {"lingmess": {k: v for k, v in map_lm.items()},
         "coreferee": {k: v for k, v in map_cf.items()}}, indent=1))
    print("saved ->", OUTD / "f5_external.json", flush=True)


if __name__ == "__main__":
    main()

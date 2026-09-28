"""E2: frozen identity ablations, core extraction, and dev-only few-shot tuning.

`run` never reads Level E gold. `dev_select` reads only old Level D dev gold;
`test` requires selected config written before it is invoked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
EC = HERE.parent / "event_canon_v1"
PL = HERE.parent / "policy_licensing_v1"
sys.path[:0] = [str(EC), str(PL)]
from ec_common import local_context, sentence_of_span
from ec_run_llm import SYSTEM_F
from ec_feats import norm_lemma
from pl_common import Mistral

FROZEN = HERE / "frozen"
OUT = HERE / "outputs"
LABELS = {"SAME_EVENT", "RELATED_BUT_DIFFERENT", "DIFFERENT", "UNKNOWN"}
SYSTEM_CORE_ID = """Decide whether two structured descriptions refer to the SAME particular event occurrence, merely related but distinct events, different events, or insufficient evidence. A check of an action is NOT that action; a result state is NOT the action. Different entities, actors, times, polarity, or repeated occurrences must not merge. Active/passive/nominal references to one event may merge. Return JSON only: {"label":"SAME_EVENT|RELATED_BUT_DIFFERENT|DIFFERENT|UNKNOWN","reason":"one short source-based reason"}."""
DEMO_IDS = [("dev_marina", "m1", "m4"), ("dev_photolab", "m1", "m4"),
            ("dev_marina", "m1", "m5"), ("dev_bakery", "m1", "m4"),
            ("dev_bakery", "m1", "m2"), ("dev_bakery", "m5", "m6"),
            ("dev_photolab", "m2", "m4"), ("dev_bakery", "m1", "m3")]


def load_test() -> list[dict]:
    return json.loads((FROZEN / "identity_inputs.json").read_text(encoding="utf-8"))


def ud_core(nlp, policy: str, mention: dict) -> dict:
    sentence, _ = sentence_of_span(policy, mention["start"])
    if not sentence:
        sentence = policy
    # sentence_of_span returns trimmed text; use exact mention alignment in it
    off = sentence.find(mention["span"])
    if off < 0:
        return {"predicate": "", "mode": "UNKNOWN", "actor": "", "patient": "", "polarity": "UNKNOWN", "time": ""}
    doc = nlp(sentence)
    toks = [(s, w) for s in doc.sentences for w in s.words
            if w.start_char >= off and w.end_char <= off + len(mention["span"])]
    if not toks:
        return {"predicate": "", "mode": "UNKNOWN", "actor": "", "patient": "", "polarity": "UNKNOWN", "time": ""}
    s, head = next(((s, w) for s, w in reversed(toks) if w.upos == "VERB"), toks[-1])
    mode = "REFERENCE" if head.upos == "NOUN" or any(w.head == head.id and w.deprel.startswith("aux:pass") for w in s.words) else "ACTION"
    if head.upos not in {"VERB", "NOUN"}:
        mode = "UNKNOWN"
    actor = patient = ""
    for w in s.words:
        if w.head != head.id:
            continue
        dep = w.deprel.split(":")[0]
        if dep in {"nsubj", "csubj"}:
            (patient if mode == "REFERENCE" else actor)  # no-op for readability
            if mode == "REFERENCE":
                patient = w.lemma or w.text
            else:
                actor = w.lemma or w.text
        elif dep in {"obj", "iobj", "obl"}:
            patient = w.lemma or w.text
    pol = "NEG" if any(w.lemma in {"not", "never", "no"} for _, w in toks) else "POS"
    time = " ".join(w.text for _, w in toks if w.upos == "NUM" or w.deprel == "obl:tmod")
    return {"predicate": norm_lemma(head.lemma or head.text), "mode": mode,
            "actor": actor, "patient": patient, "polarity": pol, "time": time}


def payload(row: dict, arm: str, nlp=None) -> dict:
    policy = row["policy"]
    a, b = row["a"], row["b"]
    ca, cb = local_context(policy, a["start"], 1), local_context(policy, b["start"], 1)
    if arm == "B1_raw":
        return {"mention_a": a["span"], "context_a": ca,
                "mention_b": b["span"], "context_b": cb}
    ka, kb = ud_core(nlp, policy, a), ud_core(nlp, policy, b)
    if arm == "B2_core":
        return {"core_a": {k: ka[k] for k in ("predicate", "mode")},
                "core_b": {k: kb[k] for k in ("predicate", "mode")}}
    if arm == "B3_raw_core":
        return {"mention_a": a["span"], "core_a": {k: ka[k] for k in ("predicate", "mode")},
                "mention_b": b["span"], "core_b": {k: kb[k] for k in ("predicate", "mode")}}
    if arm == "B4_core_sentence":
        return {"core_a": {k: ka[k] for k in ("predicate", "mode")}, "sentence_a": ca,
                "core_b": {k: kb[k] for k in ("predicate", "mode")}, "sentence_b": cb}
    if arm == "B5_raw_core_args":
        return {"mention_a": a["span"], "core_a": ka, "sentence_a": ca,
                "mention_b": b["span"], "core_b": kb, "sentence_b": cb}
    raise ValueError(arm)


def ask(client: Mistral, system: str, content: dict) -> dict:
    rec = client.ask(system, json.dumps(content, ensure_ascii=False), max_tokens=230)
    ans, err = Mistral.parse_json(rec["raw"])
    label = (ans or {}).get("label")
    label = label.upper().strip() if isinstance(label, str) else "UNKNOWN"
    if label not in LABELS:
        label = "UNKNOWN"
    return {"label": label, "reason": (ans or {}).get("reason", ""),
            "raw": rec["raw"], "usage": rec.get("usage", {}), "error": err}


def run_test_cores():
    import stanza
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse", verbose=False, use_gpu=True)
    client = Mistral(cache_dir=OUT / "_cache")
    for row in load_test():
        for arm in ("B1_raw", "B2_core", "B3_raw_core", "B4_core_sentence", "B5_raw_core_args"):
            path = OUT / "E2" / arm / (row["id"].replace("::", "__") + ".json")
            if path.exists():
                continue
            p = payload(row, arm, nlp)
            result = ask(client, SYSTEM_F if arm == "B1_raw" else SYSTEM_CORE_ID, p)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"id": row["id"], "arm": arm, "input": p,
                                        **result}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(row["id"], arm, result["label"], flush=True)
    print(json.dumps({"model": client.model, "new_calls": client.calls,
                      "usage": client.usage_total}), flush=True)


def old_dev_rows() -> tuple[list[dict], dict]:
    old = EC / "frozen"
    cases = {c["case_id"]: c for c in json.loads((old / "frozen_cases.json").read_text(encoding="utf-8"))
             if c["split"] == "dev"}
    old_gold = json.loads((old / "pairs_gold.json").read_text(encoding="utf-8"))
    examples, eg_labels = [], {}
    for cid, a, b in DEMO_IDS:
        case = cases[cid]
        ms = {m["mid"]: m for m in case["mentions"]}
        rec = next(x for x in old_gold[cid] if {x["a"], x["b"]} == {a, b})
        examples.append({"case_id": cid, "a": ms[a]["span"], "b": ms[b]["span"], "label": rec["label"]})
        eg_labels[(cid, tuple(sorted((a, b))))] = rec["label"]
    pool = []
    for cid, case in cases.items():
        ms = {m["mid"]: m for m in case["mentions"]}
        for p in old_gold[cid]:
            if (cid, tuple(sorted((p["a"], p["b"])))) in eg_labels or p["label"] == "AMBIGUOUS":
                continue
            h = hashlib.sha256(f"{cid}:{p['a']}:{p['b']}".encode()).hexdigest()
            pool.append((h, {"id": f"{cid}::{p['a']}::{p['b']}", "policy": case["policy"],
                             "a": ms[p["a"]], "b": ms[p["b"]], "label": p["label"]}))
    selected = []
    for label in ("SAME_EVENT", "RELATED_BUT_DIFFERENT", "DIFFERENT"):
        selected += [x for _, x in sorted(pool) if x["label"] == label][:12]
    return selected, examples


def fewshot_system(k: int, examples: list[dict]) -> str:
    if k == 0:
        return SYSTEM_F
    out = SYSTEM_F + "\nExamples from separate development policies:\n"
    for x in examples[:k]:
        out += json.dumps({"mention_a": x["a"], "mention_b": x["b"], "label": x["label"]}, ensure_ascii=False) + "\n"
    return out + "Classify the next pair using the same ontology."


def run_dev_fewshot():
    rows, examples = old_dev_rows()
    client = Mistral(cache_dir=OUT / "_cache")
    (OUT / "E2_dev_selection.json").write_text(json.dumps({"ids": [r["id"] for r in rows],
                                                       "examples": examples}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for k in (0, 3, 5, 8):
        system = fewshot_system(k, examples)
        for row in rows:
            path = OUT / "E2_dev" / f"k{k}" / (row["id"].replace("::", "__") + ".json")
            if path.exists():
                continue
            result = ask(client, system, payload(row, "B1_raw"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"id": row["id"], "gold": row["label"],
                                        "k": k, **result}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print("dev", k, row["id"], result["label"], flush=True)
    print(json.dumps({"model": client.model, "new_calls": client.calls,
                      "usage": client.usage_total}), flush=True)


def select_dev():
    metrics = {}
    for k in (0, 3, 5, 8):
        rows = [json.loads(p.read_text(encoding="utf-8")) for p in (OUT / "E2_dev" / f"k{k}").glob("*.json")]
        if len(rows) != len(old_dev_rows()[0]):
            raise ValueError(f"missing dev outputs k{k}")
        tp = sum(r["label"] == "SAME_EVENT" and r["gold"] == "SAME_EVENT" for r in rows)
        fp = sum(r["label"] == "SAME_EVENT" and r["gold"] != "SAME_EVENT" for r in rows)
        fn = sum(r["label"] != "SAME_EVENT" and r["gold"] == "SAME_EVENT" for r in rows)
        dangerous = sum(r["label"] == "SAME_EVENT" and r["gold"] == "RELATED_BUT_DIFFERENT" for r in rows)
        metrics[k] = {"tp": tp, "fp": fp, "fn": fn, "dangerous": dangerous,
                      "precision": tp / (tp + fp) if tp + fp else 0,
                      "recall": tp / (tp + fn) if tp + fn else 0}
    # Precision is primary; fewer dangerous merges, then recall, then fewer
    # examples. This ranking is fixed here before Level E calls.
    best = max(metrics, key=lambda k: (metrics[k]["precision"], -metrics[k]["dangerous"], metrics[k]["recall"], -k))
    payload = {"selected_k": best, "metrics": metrics, "rule": "max precision, min dangerous, max recall, min k"}
    (OUT / "E2_fewshot_selected.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


def run_selected():
    selected = json.loads((OUT / "E2_fewshot_selected.json").read_text(encoding="utf-8"))
    k = selected["selected_k"]
    _, examples = old_dev_rows()
    system = fewshot_system(k, examples)
    client = Mistral(cache_dir=OUT / "_cache")
    for row in load_test():
        path = OUT / "E2" / f"F_fewshot_k{k}" / (row["id"].replace("::", "__") + ".json")
        if path.exists():
            continue
        result = ask(client, system, payload(row, "B1_raw"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"id": row["id"], "arm": f"F_fewshot_k{k}",
                                    **result}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(row["id"], result["label"], flush=True)
    print(json.dumps({"model": client.model, "new_calls": client.calls,
                      "usage": client.usage_total}), flush=True)


def score():
    gold = json.loads((FROZEN / "identity_gold.json").read_text(encoding="utf-8"))
    inputs = {r["id"]: r for r in load_test()}
    arms = [p.name for p in (OUT / "E2").iterdir() if p.is_dir()]
    result = {}
    for arm in sorted(arms):
        rows = [json.loads(p.read_text(encoding="utf-8")) for p in (OUT / "E2" / arm).glob("*.json")]
        if {r["id"] for r in rows} != set(gold):
            raise ValueError(f"missing E2 predictions {arm}")
        tp = sum(r["label"] == "SAME_EVENT" and gold[r["id"]] == "SAME_EVENT" for r in rows)
        fp = sum(r["label"] == "SAME_EVENT" and gold[r["id"]] != "SAME_EVENT" for r in rows)
        fn = sum(r["label"] != "SAME_EVENT" and gold[r["id"]] == "SAME_EVENT" for r in rows)
        dangerous = sum(r["label"] == "SAME_EVENT" and gold[r["id"]] == "RELATED_BUT_DIFFERENT" for r in rows)
        by_id = {r["id"]: r for r in rows}
        noise_pairs = [(a, b) for a, b in ((f"{c}::noise::clean", f"{c}::noise::noisy")
                      for c in sorted({r["case_id"] for r in inputs.values()})) if a in by_id and b in by_id]
        stable = sum(by_id[a]["label"] == by_id[b]["label"] for a, b in noise_pairs)
        result[arm] = {"tp": tp, "fp": fp, "fn": fn, "precision": tp / (tp + fp) if tp + fp else 0,
                       "recall": tp / (tp + fn) if tp + fn else 0,
                       "dangerous_related_to_same": dangerous,
                       "unknown": sum(r["label"] == "UNKNOWN" for r in rows),
                       "clean_noisy_same_label": stable, "clean_noisy_pairs": len(noise_pairs),
                       "same_on_clean": sum(by_id[a]["label"] == "SAME_EVENT" for a, b in noise_pairs),
                       "same_on_noisy": sum(by_id[b]["label"] == "SAME_EVENT" for a, b in noise_pairs)}
    out = {"arms": result, "n_pairs": len(gold)}
    (OUT / "E2_score.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("phase", choices=("cores", "dev", "select", "selected", "score")); phase = ap.parse_args().phase
    {"cores": run_test_cores, "dev": run_dev_fewshot, "select": select_dev,
     "selected": run_selected, "score": score}[phase]()

"""Prospective E1 eventness arms. `run` never reads E1 gold.

A1: UD/POS structural signal; A3: old X-AMR-style extractor repurposed as
eventness diagnostic; A4: narrow LLM; A5: clear UD cases + A4 on uncertain
nominals. A2 PropBank/SRL is attempted only if a compatible model exists.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
EC = HERE.parent / "event_canon_v1"
PL = HERE.parent / "policy_licensing_v1"
sys.path[:0] = [str(EC), str(PL)]
from pl_common import Mistral
from ec_run_llm import SYSTEM_E

FROZEN = HERE / "frozen"
OUT = HERE / "outputs"
LABELS = {"EVENT", "EVENT_REFERENCE", "STATE", "ENTITY_ARTIFACT", "OTHER", "UNKNOWN"}
EVENTLIKE = {"EVENT", "EVENT_REFERENCE", "STATE"}
JUNK = {"ENTITY_ARTIFACT", "OTHER"}

SYSTEM_A4 = """Classify exactly the marked span IN ITS CONTAINING SENTENCE, not the whole sentence. JSON only: {"label":"EVENT|EVENT_REFERENCE|STATE|ENTITY_ARTIFACT|OTHER|UNKNOWN"}.
EVENT is an action/check occurrence or instruction to perform one. EVENT_REFERENCE is a nominal, passive or anaphoric reference to a particular event. STATE is a property/status that holds, including a result state; it is not itself an action. ENTITY_ARTIFACT is a person, object, identifier, document, request, report or metadata item, even when named after an event. OTHER is a quantity or non-event fragment. UNKNOWN if the context does not distinguish these. Do not promote a noun to EVENT merely because it resembles a verb; do not discard a nominal event reference merely because it is a noun. Use only the supplied exact span and sentence; no tool names or catalog."""


def load_inputs() -> list[dict]:
    return json.loads((FROZEN / "eventness_inputs.json").read_text(encoding="utf-8"))


def head_features(nlp, row: dict) -> dict:
    sentence, span = row["sentence"], row["span"]
    st = sentence.find(span)
    if st < 0:
        return {"head_upos": "UNKNOWN", "head_dep": "UNKNOWN", "label": "UNKNOWN"}
    en = st + len(span)
    doc = nlp(sentence)
    selected = []
    for s in doc.sentences:
        for w in s.words:
            if w.start_char >= st and w.end_char <= en:
                selected.append((s, w))
    if not selected:
        return {"head_upos": "UNKNOWN", "head_dep": "UNKNOWN", "label": "UNKNOWN"}
    ids = {w.id for _, w in selected}
    s, head = next(((s, w) for s, w in selected if w.head not in ids), selected[-1])
    upos, dep, lemma = head.upos, head.deprel.split(":")[0], (head.lemma or head.text).lower()
    has_passive = any(w.head == head.id and w.deprel.startswith("aux:pass") for w in s.words)
    copula = any(w.head == head.id and w.deprel == "cop" for w in s.words)
    if upos == "VERB":
        label = "EVENT_REFERENCE" if has_passive or dep in {"acl", "amod"} else "EVENT"
    elif upos in {"ADJ"} and copula:
        label = "STATE"
    elif upos in {"NUM", "SYM", "PUNCT"}:
        label = "OTHER"
    elif upos == "NOUN":
        # Generic derivational morphology is a candidate signal, not a hard
        # event decision: shipment/payment/inspection can have both readings.
        label = "UNKNOWN" if re.search(r"(tion|sion|ment|ance|ence|ing|al|ure)$", lemma) else "ENTITY_ARTIFACT"
        if len(selected) == 1:
            label = "UNKNOWN"  # single nominal can name an event instance
    else:
        label = "UNKNOWN"
    return {"head_upos": upos, "head_dep": dep, "head_lemma": lemma,
            "has_passive_aux": has_passive, "has_copula": copula,
            "selected_count": len(selected), "label": label}


def llm_label(client: Mistral, system: str, row: dict, max_tokens: int) -> tuple[str, dict]:
    query = json.dumps({"exact_span": row["span"], "containing_sentence": row["sentence"]}, ensure_ascii=False)
    rec = client.ask(system, query, max_tokens=max_tokens)
    answer, err = Mistral.parse_json(rec["raw"])
    label = (answer or {}).get("label")
    if not isinstance(label, str) or label.upper() not in LABELS:
        label = "UNKNOWN"
    return label.upper(), {"error": err, "usage": rec.get("usage", {}), "raw": rec["raw"]}


def amr_label(client: Mistral, row: dict) -> tuple[str, dict]:
    query = json.dumps({"mention": row["span"], "local_context": row["sentence"]}, ensure_ascii=False)
    rec = client.ask(SYSTEM_E, query, max_tokens=280)
    answer, err = Mistral.parse_json(rec["raw"])
    mode = (answer or {}).get("event_mode")
    label = {"ACTION": "EVENT", "CHECK": "EVENT", "COMMUNICATION": "EVENT",
             "REFERENCE": "EVENT_REFERENCE", "STATE": "STATE", "OBSERVATION": "STATE"}.get(mode, "UNKNOWN")
    return label, {"error": err, "graph": answer or {}, "usage": rec.get("usage", {}), "raw": rec["raw"]}


def run():
    import stanza
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse", verbose=False, use_gpu=True)
    client = Mistral(cache_dir=OUT / "_cache")
    rows = load_inputs()
    for row in rows:
        dst = OUT / "E1" / (row["id"].replace("::", "__") + ".json")
        if dst.exists():
            continue
        ud = head_features(nlp, row)
        a4, a4_raw = llm_label(client, SYSTEM_A4, row, 120)
        a3, a3_raw = amr_label(client, row)
        a5 = ud["label"] if ud["label"] in {"EVENT", "EVENT_REFERENCE", "STATE", "OTHER"} else a4
        payload = {"id": row["id"], "input": row, "A1_ud": ud["label"], "A1_features": ud,
                   "A2_srl": "UNAVAILABLE", "A3_amr": a3, "A4_llm": a4,
                   "A5_hybrid": a5, "A3_record": a3_raw, "A4_record": a4_raw}
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(row["id"], ud["label"], a4, a3, flush=True)
    print(json.dumps({"model": client.model, "new_calls": client.calls,
                      "usage": client.usage_total}), flush=True)


def score():
    gold = json.loads((FROZEN / "eventness_gold.json").read_text(encoding="utf-8"))
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((OUT / "E1").glob("*.json"))]
    if {x["id"] for x in rows} != set(gold):
        raise ValueError("missing E1 predictions")
    result = {}
    for arm in ("A1_ud", "A3_amr", "A4_llm", "A5_hybrid"):
        pairs = [(gold[r["id"]], r[arm]) for r in rows if gold[r["id"]] != "AMBIGUOUS"]
        matrix = {g: dict(Counter(p for gg, p in pairs if gg == g)) for g in sorted({x[0] for x in pairs})}
        real_total = sum(g in EVENTLIKE for g, _ in pairs)
        junk_total = sum(g in JUNK for g, _ in pairs)
        real_lost = sum(g in EVENTLIKE and p in JUNK for g, p in pairs)
        junk_removed = sum(g in JUNK and p in JUNK for g, p in pairs)
        admitted = [(g, p) for g, p in pairs if p in EVENTLIKE]
        result[arm] = {"confusion": matrix, "real_total": real_total,
                       "junk_total": junk_total, "real_lost": real_lost,
                       "junk_removed": junk_removed,
                       "eventlike_precision": sum(g in EVENTLIKE for g, _ in admitted) / len(admitted) if admitted else None,
                       "eventlike_recall": sum(g in EVENTLIKE and p in EVENTLIKE for g, p in pairs) / real_total if real_total else None,
                       "unknown": sum(p == "UNKNOWN" for _, p in pairs)}
    output = {"arms": result, "cases": len(rows), "ambiguous_gold_excluded": sum(v == "AMBIGUOUS" for v in gold.values())}
    (OUT / "E1_score.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("phase", choices=("run", "score")); args = ap.parse_args()
    (run if args.phase == "run" else score)()

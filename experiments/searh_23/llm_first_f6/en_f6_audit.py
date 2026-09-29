"""F6 ARM C — NLP structural coverage audit (watchdog, NOT a filter).

The NLP layer NEVER creates a mandatory candidate set (directive
section 7). It only proposes structural anchors:

  - verb anchors: upos VERB excluding aux/cop dependencies
  - deverbal noun anchors: upos NOUN whose lemma equals a verb lemma in
    the same document, or carries a derivational nominalization suffix
    (-tion/-sion/-ment/-ing/-al/-ance/-ence/-ure)
  - participle-adjective anchors: upos ADJ/VERB participles attached via
    amod/psas/acl to a noun

An anchor is COVERED when at least one LLM semantic mention overlaps it
by >=1 character. UNCOVERED anchors are the audit signal: 'possibly
missed semantic content' - never an automatic error.

Signal evaluation vs gold:
  gold event mention g (cid non-null) is MISSED by the LLM when no LLM
  mention overlaps g. The audit DETECTS g when an UNCOVERED anchor
  overlaps g. Anchor-level:
    TP = uncovered anchor overlapping >=1 missed gold event mention
    FP = uncovered anchor overlapping no gold event mention
  Mention-level detection recall = detected missed / all missed.

Also: per-anchor-kind noise breakdown (directive section 7: 'which NLP
anchor types are especially noisy').

Run: python3 en_f6_audit.py   (writes outputs/audit/)
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

FROZEN = HERE / "f6_frozen"
IE = HERE.parent / "event_ie_frontends_v1"
RAW = HERE / "outputs" / "raw"
OUT = HERE / "outputs" / "audit"
OUT.mkdir(parents=True, exist_ok=True)

NOM_SUFFIXES = ("tion", "sion", "ment", "ance", "ence", "ure", "al")


def load_cases(suite: str = "f6") -> list[dict]:
    fname = {"f6": "level_f6_cases.json",
             "f6r": "level_f6r_cases.json"}[suite]
    return json.loads((IE / "frozen" / fname).read_text(encoding="utf-8"))


def extract_anchors(policy: str, doc) -> list[dict]:
    """Structural predicate anchors with char offsets (no semantics)."""
    anchors = []
    seen_spans: set[tuple[int, int]] = set()

    def add(w, kind, why):
        key = (w.start_char, w.end_char)
        if key in seen_spans or w.start_char < 0:
            return
        seen_spans.add(key)
        anchors.append({"text": w.text, "start": w.start_char,
                        "end": w.end_char, "lemma": w.lemma,
                        "kind": kind, "why": why})

    verb_lemmas = set()
    for s in doc.sentences:
        for w in s.words:
            if w.upos == "VERB" and w.deprel not in ("aux", "cop",
                                                     "aux:pass"):
                verb_lemmas.add(w.lemma.lower())
    for s in doc.sentences:
        for w in s.words:
            lem = (w.lemma or "").lower()
            if w.upos == "VERB" and w.deprel not in ("aux", "cop",
                                                     "aux:pass"):
                add(w, "verb", "non-aux verb")
            elif w.upos == "NOUN" and w.upos != "PROPN":
                if lem and lem in verb_lemmas:
                    add(w, "verbal_noun", "lemma matches doc verb")
                elif lem.endswith(NOM_SUFFIXES) and len(lem) > 5:
                    add(w, "nominalization", "derivational suffix")
            elif w.upos in ("ADJ", "VERB") and w.deprel in ("amod", "acl",
                                                            "psas"):
                if lem and (lem in verb_lemmas or w.upos == "VERB"):
                    add(w, "participle", "attached participle")
    anchors.sort(key=lambda a: a["start"])
    return anchors


def overlap(a: dict, b: dict) -> int:
    return max(0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def audit_case(case: dict, llm_mentions: list[dict],
               anchors: list[dict]) -> dict:
    gold_events = [m for m in case["mentions"] if m.get("cid")]
    cov = []
    for a in anchors:
        covered_by = [m["quote"] for m in llm_mentions
                      if overlap(a, {"start": m["start"],
                                     "end": m["end"]}) > 0]
        gold_hits = [g["span"] for g in gold_events
                     if overlap(a, g) > 0]
        cov.append({**a, "covered": bool(covered_by),
                    "covered_by": covered_by[:3],
                    "gold_event_overlap": gold_hits[:3]})
    missed = []
    for g in gold_events:
        hit = [m["quote"] for m in llm_mentions
               if overlap(g, {"start": m["start"], "end": m["end"]}) > 0]
        if not hit:
            detected = any(not c["covered"] and overlap(g, c) > 0
                           for c in cov)
            missed.append({"span": g["span"], "cid": g["cid"],
                           "detected_by_audit": detected})
    tp = sum(1 for c in cov if not c["covered"] and c["gold_event_overlap"])
    fp = sum(1 for c in cov if not c["covered"]
             and not c["gold_event_overlap"])
    return {"case_id": case["case_id"],
            "n_anchors": len(anchors), "n_uncovered": tp + fp,
            "anchors": cov, "missed_gold": missed,
            "n_missed_gold": len(missed),
            "n_missed_detected": sum(1 for m in missed if m["detected_by_audit"]),
            "anchor_tp": tp, "anchor_fp": fp,
            "uncovered_examples": [c["text"] for c in cov
                                   if not c["covered"]][:12]}


def main() -> None:
    import os
    os.environ.setdefault("HF_HOME", "/home/z/my-project/hf_cache")
    import stanza
    nlp = stanza.Pipeline("en",
                          processors="tokenize,pos,lemma,depparse",
                          verbose=False, use_gpu=False)
    cases = load_cases("f6")
    docs = {c["case_id"]: nlp(c["policy"]) for c in cases}
    summary = {}
    for model_key in ("mistral", "codestral"):
        for arm in ("A", "B"):
            rows = []
            tot = Counter()
            for case in cases:
                f = RAW / model_key / arm / f"{case['case_id']}.json"
                if not f.exists():
                    continue
                data = json.loads(f.read_text(encoding="utf-8"))
                mentions = [m for m in data["mentions"] if m["grounded"]]
                anchors = extract_anchors(case["policy"],
                                          docs[case["case_id"]])
                row = audit_case(case, mentions, anchors)
                rows.append(row)
                tot["anchors"] += row["n_anchors"]
                tot["uncovered"] += row["n_uncovered"]
                tot["anchor_tp"] += row["anchor_tp"]
                tot["anchor_fp"] += row["anchor_fp"]
                tot["missed"] += row["n_missed_gold"]
                tot["missed_detected"] += row["n_missed_detected"]
            key = f"{model_key}_{arm}"
            OUT.write_text  # keep dir
            (OUT / f"audit_{key}.json").write_text(
                json.dumps({"rows": rows, "total": dict(tot)}, indent=1,
                           ensure_ascii=False) + "\n", encoding="utf-8")
            p = tot["anchor_tp"] / max(1, tot["anchor_tp"] + tot["anchor_fp"])
            r = tot["missed_detected"] / max(1, tot["missed"])
            f1 = 2 * p * r / max(1e-9, p + r)
            summary[key] = {"anchors": tot["anchors"],
                            "uncovered": tot["uncovered"],
                            "anchor_tp": tot["anchor_tp"],
                            "anchor_fp": tot["anchor_fp"],
                            "anchor_precision": round(p, 3),
                            "missed_gold": tot["missed"],
                            "missed_detected": tot["missed_detected"],
                            "detection_recall": round(r, 3),
                            "audit_f1": round(f1, 3)}
            print(key, summary[key], flush=True)
    # noise per anchor kind (mistral A)
    kinds = Counter()
    kind_tp = Counter()
    for row in json.loads((OUT / "audit_mistral_A.json")
                          .read_text())["rows"]:
        for a in row["anchors"]:
            if not a["covered"]:
                kinds[a["kind"]] += 1
                if a["gold_event_overlap"]:
                    kind_tp[a["kind"]] += 1
    summary["noise_by_kind_mistral_A"] = {
        k: {"uncovered": kinds[k], "with_gold_overlap": kind_tp[k]}
        for k in kinds}
    (OUT / "audit_summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

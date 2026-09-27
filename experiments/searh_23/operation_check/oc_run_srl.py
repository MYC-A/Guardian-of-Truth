"""Arm D: PropBank SRL event candidates and argument structure (allennlp).

Runs the structured-prediction-srl-bert predictor per sentence. Event
candidates: verb predicates with spans extended over an adjacent ARG1;
ARGM-CND/TMP/PRP modifier contents become additional (nominal) candidates.
Role hypothesis (generic, argument-structure based only):
  predicate with ARG0 or ARG1 -> OPERATION_EFFECT
  ARGM-CND content            -> PRECONDITION_CHECK
  other ARGM contents         -> UNKNOWN (span candidate only)
Edges: predicate with ARGM-CND/TMP -> (ARGM content) GATE/ORDER_BEFORE (predicate).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from oc_common import load_suite, out_dir, write_usage, suffix_for


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def word_offsets(sentence: str, words: list[str]):
    """Map spacy words to char offsets by sequential search."""
    out = []
    pos = 0
    for w in words:
        idx = sentence.find(w, pos)
        if idx < 0:  # fallback: search from start (rare normalisation cases)
            idx = sentence.find(w)
        if idx < 0:
            out.append((None, None))
            continue
        out.append((idx, idx + len(w)))
        pos = idx + len(w)
    return out


def tag_ranges(tags: list[str]) -> dict[str, list[int]]:
    """BIO tags -> contiguous token index ranges per role label."""
    ranges = {}
    current = None
    start = -1
    for i, tag in enumerate(tags + ["O"]):
        if tag.startswith("B-"):
            if current is not None:
                ranges.setdefault(current, []).append((start, i - 1))
            current = tag[2:]
            start = i
        elif tag.startswith("I-") and current == tag[2:]:
            continue
        elif tag.startswith("I-"):
            if current is not None:
                ranges.setdefault(current, []).append((start, i - 1))
            current = tag[2:]
            start = i
        else:  # O
            if current is not None:
                ranges.setdefault(current, []).append((start, i - 1))
                current = None
    return ranges


ARGM_CONDITION = {"ARGM-CND"}
ARGM_OTHER = {"ARGM-TMP", "ARGM-PRP", "ARGM-ADV", "ARGM-PNC", "ARGM-CAU", "ARGM-CON"}


def analyse_sentence(sentence: str, pred_out: dict):
    words = pred_out.get("words", [])
    offs = word_offsets(sentence, words)
    events, edges = [], []
    for v in pred_out.get("verbs", []):
        tags = v.get("tags", [])
        ranges = tag_ranges(tags)
        verb_idx = None
        for i, w in enumerate(words):
            if offs[i][0] is not None and w == v.get("verb") and tags[i].startswith("B-V"):
                verb_idx = i
                break
        if verb_idx is None:
            continue
        arg1 = ranges.get("ARG1", [])
        arg0 = ranges.get("ARG0", [])
        span_range = None
        if arg1:
            a, b = arg1[0]
            lo, hi = min(verb_idx, a), max(verb_idx, b)
            if offs[lo][0] is None or offs[hi][0] is None:
                span_range = (verb_idx, verb_idx)
            else:
                span_range = (lo, hi)
        else:
            span_range = (verb_idx, verb_idx)
        lo, hi = span_range
        if offs[lo][0] is None:
            continue
        span = sentence[offs[lo][0]: offs[hi][1]]
        role = "OPERATION_EFFECT" if (arg0 or arg1) else "UNKNOWN"
        events.append({"span": span, "verb": v.get("verb"),
                       "arg0": bool(arg0), "arg1": bool(arg1),
                       "role_hypothesis": role})

        for argm in ARGM_CONDITION | ARGM_OTHER:
            for a, b in ranges.get(argm, []):
                if offs[a][0] is None:
                    continue
                cspan = sentence[offs[a][0]: offs[b][1]]
                # strip a leading preposition/conjunction token from the span text
                stripped = re.sub(r"^(?:after|before|if|unless|when|once|until|even|during)\s+",
                                  "", cspan, flags=re.IGNORECASE)
                cstart = offs[a][0] + (len(cspan) - len(stripped))
                cspan_final = sentence[cstart: offs[b][1]] if cspan != stripped else cspan
                if not cspan_final.strip():
                    continue
                crole = "PRECONDITION_CHECK" if argm in ARGM_CONDITION else "UNKNOWN"
                events.append({"span": cspan_final, "verb": None,
                               "argm_type": argm, "role_hypothesis": crole})
                rel = "GATE" if argm in ARGM_CONDITION else "ORDER_BEFORE"
                edges.append({"condition_span": cspan_final, "operation_span": span,
                              "relation": rel, "source": f"srl:{argm}"})
    return events, edges


def main():
    which = os.environ.get("OC_SUITE", "original")
    arm = os.environ.get("OC_ARM_DIR", "D_srl")
    suite = load_suite(which)
    from allennlp.predictors.predictor import Predictor
    predictor = Predictor.from_path(
        "/workspace/guardian/models/allennlp/structured-prediction-srl-bert.2020.12.15.tar.gz",
        cuda_device=-1)
    t0 = time.time()
    outdir = out_dir(arm + suffix_for(which))
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            continue
        events, edges = [], []
        for sent in split_sentences(case["policy"]):
            out = predictor.predict(sentence=sent)
            evs, eds = analyse_sentence(sent, out)
            events.extend(evs)
            edges.extend(eds)
        result = {"case_id": case["case_id"], "events": events, "edges": edges}
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    write_usage(arm + suffix_for(which),
                {"wall_seconds": round(time.time() - t0, 1), "suite": which,
                 "model": "allennlp structured-prediction-srl-bert.2020.12.15 (cpu)",
                 "device": "cpu"})
    print("D done", which)


if __name__ == "__main__":
    main()

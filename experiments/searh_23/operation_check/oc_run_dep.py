"""Arm B: dependency-parser event candidates and structural features (stanza).

Extracts verb-headed clause candidates with UD features (clause function,
subordination mark, deontic aux, polarity, voice) and a FROZEN structural
role hypothesis that uses only UD relations and closed-class function words:

  root clause, non-copula            -> OPERATION_EFFECT
  root clause with copula predicate  -> STATE_OBSERVATION
  advcl/acl with mark in
    {if, unless, until, once}        -> PRECONDITION_CHECK
  advcl with mark in {before, after, when} -> OPERATION_EFFECT
  everything else                    -> UNKNOWN

Edges come from UD marks (generic function-word -> relation map):
  mark on C (head H): if -> C GATE H; unless -> C EXCEPTION H;
  before -> H ORDER_BEFORE C; after/when -> C ORDER_BEFORE H / ORDER_AFTER H;
  even+if -> C EVEN_IF H.
No domain word lists are used anywhere.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from oc_common import load_suite, out_dir, write_usage

COND_MARKS = {"if", "unless", "until", "once"}
TEMP_MARKS = {"before", "after", "when"}
DEONTIC = {"must", "shall", "may", "might", "can", "could", "should", "will", "would"}
# closed-class function words only (grammatical, not domain vocabulary)

MARK_RELATION = {
    "if": ("GATE", "cond"),
    "unless": ("EXCEPTION", "cond"),
    "until": ("GATE", "cond"),
    "once": ("GATE", "cond"),
    "when": ("ORDER_AFTER", "cond"),
    "before": ("ORDER_BEFORE", "head"),
    "after": ("ORDER_BEFORE", "sub"),
}


def clause_span(doc, sentence, head_id):
    """Maximal token span of the subtree of head_id within the sentence."""
    tokens = [t for t in sentence.tokens]
    by_id = {t.id[0]: t for t in tokens}

    def subtree_ids(tid, seen=None):
        if seen is None:
            seen = set()
        if tid in seen:
            return seen
        seen.add(tid)
        for t in tokens:
            if t.head == tid and t.id[0] not in seen:
                subtree_ids(t.id[0], seen)
        return seen

    ids = sorted(subtree_ids(head_id))
    start_char = tokens[ids[0] - 1].start_char
    end_char = tokens[ids[-1] - 1].end_char
    text = sentence.text
    # trim trailing/leading punctuation and coordinating conjunctions
    while ids:
        tok = tokens[ids[0] - 1]
        if tok.upos in {"PUNCT", "CCONJ"} and tok.id[0] != head_id:
            ids = ids[1:]
            start_char = tokens[ids[0] - 1].start_char
        else:
            break
    while ids:
        tok = tokens[ids[-1] - 1]
        if tok.upos in {"PUNCT", "CCONJ"} and tok.id[0] != head_id:
            ids = ids[:-1]
            end_char = tokens[ids[-1] - 1].end_char
        else:
            break
    span = text[start_char - sentence.start_char: end_char - sentence.start_char]
    return start_char, end_char, span


def np_candidates(sentence, words, verb):
    """Nominal argument candidates of a verb: obj/obl/nsubj subtrees that
    contain no nested verb (non-clausal), conj-split into separate NPs.
    Structural only; roles stay UNKNOWN (grounding will label them)."""
    out = []
    by_id = {w.id: w for w in words}

    def subtree_tokens(tid, seen=None):
        if seen is None:
            seen = set()
        if tid in seen:
            return []
        seen.add(tid)
        result = [by_id[tid]]
        for w in words:
            if w.head == tid and w.id not in seen:
                result.extend(subtree_tokens(w.id, seen))
        return result

    for child in words:
        if child.head != verb.id:
            continue
        rel = child.deprel.split(":")[0]
        if rel not in {"obj", "iobj", "obl", "nsubj"}:
            continue
        toks = subtree_tokens(child.id)
        if any(t.upos in {"VERB", "AUX", "SCONJ"} and t.id != child.id for t in toks):
            continue  # clausal argument, not a plain NP
        if child.upos in {"PRON", "DET"} and len(toks) <= 1:
            continue
        # conj split: NPs conjoined to this NP head (conj attaches to it)
        conjs = [c for c in words
                 if c.head == child.id and c.deprel == "conj"]
        case_lemma = None
        for c in words:
            if c.head == child.id and c.deprel == "case":
                case_lemma = c.lemma
        members = [child] + [c for c in conjs
                             if not any(t.upos in {"VERB", "AUX"} for t in subtree_tokens(c.id))]
        for m in members:
            mtoks = subtree_tokens(m.id)
            if not mtoks:
                continue
            ids = sorted(t.id for t in mtoks)
            st = sentence.tokens[ids[0] - 1].start_char
            en = sentence.tokens[ids[-1] - 1].end_char
            while ids:
                tok = sentence.tokens[ids[0] - 1]
                if tok.upos in {"PUNCT", "CCONJ", "DET", "ADP"} and tok.id[0] != m.id:
                    ids = ids[1:]
                    if not ids:
                        break
                    st = sentence.tokens[ids[0] - 1].start_char
                else:
                    break
            while ids:
                tok = sentence.tokens[ids[-1] - 1]
                if tok.upos in {"PUNCT", "CCONJ"} and tok.id[0] != m.id:
                    ids = ids[:-1]
                    en = sentence.tokens[ids[-1] - 1].end_char
                else:
                    break
            span = sentence.text[st - sentence.start_char: en - sentence.start_char]
            if span.strip() and len(span.split()) >= 2:
                out.append({"span": span, "np_of_verb": verb.lemma,
                            "dep_in_verb": rel, "case_lemma": case_lemma,
                            "role_hypothesis": "UNKNOWN", "is_np": True})
    return out


CLAUSE_DEPS = {"root", "advcl", "acl", "ccomp", "xcomp", "conj", "parataxis"}


def analyse_case(nlp, case):
    policy = case["policy"]
    doc = nlp(policy)
    events = []
    clause_heads = []  # (word, sentence, head_word, record)

    for s_idx, sentence in enumerate(doc.sentences):
        words = [w for w in sentence.words]
        by_id = {w.id: w for w in words}
        for w in words:
            dep = w.deprel.split(":")[0]
            if dep not in CLAUSE_DEPS:
                continue
            has_cop = any(c.deprel == "cop" for c in words if c.head == w.id)
            if w.upos != "VERB" and not has_cop:
                continue
            head = by_id.get(w.head)
            # mark / aux children of THIS verb's clause
            marks = [c.lemma for c in words
                     if c.head == w.id and c.deprel in {"mark", "case"} and c.upos == "SCONJ"]
            aux_kids = [c for c in words if c.head == w.id and c.deprel in {"aux", "aux:pass"}]
            deontic = [c.lemma for c in aux_kids if c.lemma in DEONTIC]
            neg = any(c.deprel == "advmod" and c.lemma in {"not", "never", "no"}
                      for c in words if c.head == w.id)
            passive = any(c.deprel == "aux:pass" for c in aux_kids)
            imperative = False
            for t in sentence.tokens:
                if t.id[0] == w.id:
                    feats = t.feats or {}
                    if isinstance(feats, dict):
                        mood = feats.get("Mood", [])
                        if isinstance(mood, str):
                            mood = [mood]
                        imperative = any(m == "Imp" for m in mood)
                    break
            is_root = dep == "root"
            copula_root = any(c.deprel == "cop" and c.upos == "AUX" and c.lemma == "be"
                              for c in words if c.head == w.id) and is_root
            # event-level "even" modifier for even-if
            even = any(c.lemma == "even" for c in words if c.head == w.id)
            start, end, span = clause_span(doc, sentence, w.id)
            if not span.strip():
                continue

            if has_cop:
                role = "STATE_OBSERVATION"
            elif dep in {"advcl", "acl", "advmod"} and marks:
                m = marks[0]
                if m in COND_MARKS:
                    role = "PRECONDITION_CHECK"
                elif m in TEMP_MARKS:
                    role = "OPERATION_EFFECT"
                else:
                    role = "UNKNOWN"
            elif dep in {"ccomp", "xcomp", "conj", "parataxis"}:
                role = "UNKNOWN"
            else:
                # root or any unmarked clause with deontic/imperative force
                role = "OPERATION_EFFECT" if (is_root or deontic or imperative) else "UNKNOWN"

            rec = {
                "span": span,
                "start": start, "end": end,
                "verb": w.lemma,
                "dep": dep,
                "copula": bool(has_cop),
                "mark": marks[0] if marks else None,
                "deontic": deontic,
                "neg": neg,
                "passive": passive,
                "imperative": bool(imperative),
                "root": is_root,
                "role_hypothesis": role,
                "head_verb": head.lemma if head and head.upos == "VERB" else None,
                "head_word": head.lemma if head else None,
                "even": even,
            }
            events.append(rec)
            clause_heads.append((w, s_idx, head, rec))
            # nominal argument candidates (obj/obl/nsubj NPs, conj-split)
            events.extend(np_candidates(sentence, words, w))

    # edges from UD marks between clause heads
    edges = []
    head_keys = {(hw.id, hs) for hw, hs, _h, _r in clause_heads}
    for w, s_idx, head, rec in clause_heads:
        if not rec["mark"] or not rec["head_verb"]:
            continue
        if head is None or (head.id, s_idx) not in head_keys:
            continue
        m = rec["mark"]
        if m not in MARK_RELATION:
            continue
        rel, direction = MARK_RELATION[m]
        if rec["even"] and m == "if":
            rel = "EVEN_IF"
        # find the head clause record (match by head word id within sentence)
        head_rec = None
        for hw, hs, _h, hrec in clause_heads:
            if hw.id == head.id and hs == s_idx and hrec is not rec:
                head_rec = hrec
                break
        if head_rec is None:
            continue
        if direction == "cond":
            cond_span, op_span = rec["span"], head_rec["span"]
        elif direction == "head":
            cond_span, op_span = head_rec["span"], rec["span"]
        else:  # sub
            cond_span, op_span = rec["span"], head_rec["span"]
        edges.append({"condition_span": cond_span, "operation_span": op_span,
                      "relation": rel, "source": f"mark:{m}"})

    return {"case_id": case["case_id"], "events": events, "edges": edges}


def main():
    which = os.environ.get("OC_SUITE", "original")
    arm = os.environ.get("OC_ARM_DIR", "B_dependency")
    suite = load_suite(which)
    import stanza
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse",
                          verbose=False, use_gpu=True)
    t0 = time.time()
    outdir = out_dir(arm + ("_renamed" if which == "renamed" else ""))
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            continue
        result = analyse_case(nlp, case)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    write_usage(arm + ("_renamed" if which == "renamed" else ""),
                {"wall_seconds": round(time.time() - t0, 1),
                 "suite": which, "model": "stanza en (tokenize,pos,lemma,depparse)",
                 "gpu": True})
    print("B done", which)


if __name__ == "__main__":
    main()

"""EVENT_CANON_v1 - shared feature extraction for local arms.

Generic mechanisms only: token lemmatization via suffix stripping (English
morphology), UD-derived event signatures (stanza), candidate generation
(blocking) optimized for recall. No domain word lists, no thresholds on
specific cases.
"""
from __future__ import annotations

import re

STOPWORDS = {
    "the", "a", "an", "each", "every", "any", "all", "both", "is", "are",
    "was", "were", "be", "been", "being", "by", "of", "to", "in", "on", "at",
    "for", "with", "and", "or", "but", "so", "as", "it", "its", "this",
    "that", "these", "those", "must", "may", "might", "can", "could",
    "should", "shall", "will", "would", "only", "after", "before", "when",
    "whenever", "if", "unless", "once", "until", "while", "since", "because",
    "than", "then", "there", "here", "which", "who", "whom", "whose", "not",
    "no", "yes", "do", "does", "did", "done", "has", "have", "had", "again",
    "separately", "instead", "well", "too", "very", "just", "also",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
SUFFIXES = ["ation", "ition", "tion", "sion", "ion", "ment", "ance", "ence",
            "ure", "al", "ing", "ed", "es", "s"]


def norm_lemma(word: str) -> str:
    """Lowercase + generic derivational/inflectional suffix stripping."""
    w = word.lower().strip()
    for suf in SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def content_tokens(span: str):
    return [norm_lemma(t) for t in _WORD_RE.findall(span)
            if norm_lemma(t) not in STOPWORDS and len(norm_lemma(t)) > 1]


def lemma_family_match(w1: str, w2: str) -> bool:
    """True if two normalized forms plausibly share a predicate family."""
    if not w1 or not w2:
        return False
    if w1 == w2:
        return True
    if len(w1) >= 4 and len(w2) >= 4:
        if w1.startswith(w2) or w2.startswith(w1):
            return True
        # vowel-adjusted prefix overlap (inspect/inspec, proofing/proof)
        n = 0
        while (n < len(w1) and n < len(w2) and w1[n] == w2[n]):
            n += 1
        return n >= 4 and abs(len(w1) - len(w2)) <= 3
    return False


def overlap_coeff(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def tokens_in_span(doc, start: int, end: int):
    """Stanza tokens fully inside [start, end)."""
    toks = []
    for s in doc.sentences:
        for w in s.words:
            if w.start_char >= start and w.end_char <= end:
                toks.append((s, w))
    return toks


def ud_signature(policy: str, doc, start: int, end: int):
    """UD-derived event signature for a mention span (arm D features)."""
    toks = tokens_in_span(doc, start, end)
    if not toks:
        return {"predicate": "", "voice": "UNKNOWN", "polarity": "POS",
                "args": [], "mods": [], "entities": [], "modality": None,
                "temporal": None, "has_head": False}
    s0, w0 = toks[0]
    sentence_words = [w for _, w in toks]
    ids = {w.id for w in sentence_words}
    sent_words = s0.words
    TEMP_PREPS = {"before", "after", "upon", "until", "once", "during",
                  "at", "on", "in", "within"}
    # head = last verb in span, else rightmost noun
    verb = None
    for w in sentence_words:
        if w.upos == "VERB":
            verb = w
    if verb is None:
        for w in reversed(sentence_words):
            if w.upos in ("NOUN", "PROPN"):
                verb = w
                break
    if verb is None:
        verb = sentence_words[-1]
    has_head = verb.upos == "VERB"
    voice = "PASSIVE" if any(
        w.deprel.startswith("aux:pass") and w.head == verb.id
        for w in sent_words) else "ACTIVE"
    polarity = "NEG" if any(
        w.lemma in ("not", "no", "never") or w.text.lower() in ("not", "never")
        for w in sentence_words) else "POS"
    args, mods, entities = [], [], []

    def case_of(w):
        for c in sent_words:
            if c.head == w.id and c.deprel == "case":
                return (c.lemma or c.text).lower()
        return None

    for w in sent_words:
        if w.id == verb.id:
            continue
        rel = w.deprel.split(":")[0]
        nm = norm_lemma(w.lemma or w.text)
        if rel in ("obj", "iobj", "nsubj") and w.id in ids:
            if nm not in STOPWORDS and len(nm) > 1:
                args.append(nm)
        elif rel in ("obl", "nmod") and w.id in ids:
            prep = case_of(w)
            if prep in TEMP_PREPS or prep in ("of", "by"):
                # 'of' keeps the patient; 'by' the agent; temporal pp skipped
                if prep == "of" and nm not in STOPWORDS and len(nm) > 1:
                    args.append(nm)
                elif prep == "by" and nm not in STOPWORDS and len(nm) > 1:
                    args.append(nm)
            elif prep is None and nm not in STOPWORDS and len(nm) > 1:
                args.append(nm)
        elif rel == "amod" and w.id in ids and w.upos == "ADJ":
            if nm not in STOPWORDS and len(nm) > 1:
                mods.append(nm)
        elif rel == "compound" and w.id in ids:
            pass  # compound noun modifiers are descriptive, not collected
        if (w.upos == "PROPN" or (w.text[:1].isupper() and w.upos == "NOUN")
                or (w.upos == "NUM" and w.id in ids)):
            nm2 = (w.lemma or w.text).lower()
            if nm2 not in STOPWORDS:
                entities.append(nm2)
    modality = None
    for w in sent_words:
        if w.deprel.startswith("aux") and w.head == verb.id and \
                (w.lemma or "").lower() in ("must", "shall", "may", "can",
                                            "should", "will", "would"):
            modality = (w.lemma or w.text).lower()
    temporal = None
    for w in sent_words:
        if w.id in ids and (w.lemma or w.text).lower() in (
                "before", "after", "upon", "until", "once", "again",
                "monday", "tuesday", "wednesday", "thursday", "friday",
                "saturday", "sunday", "morning", "afternoon", "evening",
                "january", "february", "march", "april", "may", "june",
                "july", "august", "september", "october", "november",
                "december", "hour", "day", "week", "month"):
            temporal = (w.lemma or w.text).lower()
            break
    pred = norm_lemma(verb.lemma or verb.text)
    return {"predicate": pred, "voice": voice, "polarity": polarity,
            "args": sorted(set(args)), "mods": sorted(set(mods)),
            "entities": sorted(set(entities)), "modality": modality,
            "temporal": temporal, "has_head": has_head}


def _noun_args_conflict(a: set, b: set) -> bool:
    """True if the noun-argument sets are incompatible (neither subset,
    or disjoint) - both non-empty required."""
    if not a or not b:
        return False
    return not (a <= b or b <= a)


def signature_compare(sig_a: dict, sig_b: dict):
    """Deterministic UD-signature pair decision (arm D core).

    Ontology-aligned general rules (no domain words):
      predicate-family mismatch            -> DIFFERENT
      polarity / entity / temporal /
      noun-arg conflicts (same predicate)  -> RELATED_BUT_DIFFERENT
      restrictive adjective-modifier diff  -> RELATED_BUT_DIFFERENT
      otherwise (voice-agnostic)           -> SAME_EVENT
    """
    if not sig_a["predicate"] or not sig_b["predicate"]:
        return "UNKNOWN", "no-head"
    if not lemma_family_match(sig_a["predicate"], sig_b["predicate"]):
        return "DIFFERENT", "predicate-mismatch"
    if sig_a["polarity"] != sig_b["polarity"]:
        return "RELATED_BUT_DIFFERENT", "polarity-conflict"
    ea, eb = set(sig_a["entities"]), set(sig_b["entities"])
    if ea and eb and not (ea & eb):
        return "RELATED_BUT_DIFFERENT", "entity-conflict"
    ta, tb = sig_a.get("temporal"), sig_b.get("temporal")
    if ta and tb and ta != tb:
        return "RELATED_BUT_DIFFERENT", "temporal-conflict"
    aa, ab = set(sig_a["args"]), set(sig_b["args"])
    if _noun_args_conflict(aa, ab):
        return "RELATED_BUT_DIFFERENT", "arg-conflict"
    ma, mb = set(sig_a.get("mods", [])), set(sig_b.get("mods", []))
    if ma != mb:
        return "RELATED_BUT_DIFFERENT", "restrictive-modifier"
    return "SAME_EVENT", "sig-compatible"


def candidate_pairs(mentions, embeddings=None, sim_topk=3, sent_window=1,
                    embed_thresh=0.0):
    """Blocking for LLM arms: union of locality / lexical / embedding signals.

    Optimized for recall; frozen after tuning on dev only.
    """
    by_mid = {m["mid"]: m for m in mentions}
    mids = [m["mid"] for m in mentions]
    cand = set()
    # locality
    for i in range(len(mids)):
        for j in range(i + 1, len(mids)):
            a, b = by_mid[mids[i]], by_mid[mids[j]]
            if abs(a["sentence_index"] - b["sentence_index"]) <= sent_window:
                cand.add((a["mid"], b["mid"]))
    # lexical overlap
    toks = {m["mid"]: set(content_tokens(m["span"])) for m in mentions}
    for i in range(len(mids)):
        for j in range(i + 1, len(mids)):
            if toks[mids[i]] & toks[mids[j]]:
                cand.add((mids[i], mids[j]))
    # embedding top-k
    if embeddings is not None and len(mids) > 1:
        import numpy as np
        V = np.stack([embeddings[m] for m in mids])
        V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
        S = V @ V.T
        for i in range(len(mids)):
            order = np.argsort(-S[i])
            for j in order[: sim_topk + 1]:
                if int(j) != i and S[i][j] >= embed_thresh:
                    cand.add(tuple(sorted((mids[i], mids[int(j)]))))
    return sorted(cand)

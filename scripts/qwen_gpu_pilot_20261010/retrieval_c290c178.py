"""Deterministic rule retrieval (no model call): split policy into rule units, rank by TF-IDF cosine over word uni/bi-grams and
hashed char 4-grams (a MinHash-like lexical-semantic signature) against the current move (tool name, argument keys/values,
text). Language-agnostic (char n-grams) so RU/EN rows behave the same. Not tuned per set."""
import math, re
from collections import Counter

WORD = re.compile(r'\w+', re.U)
CUE = re.compile(r'\b(must|never|only|before|always|cannot|can\'t|not allowed|should not|do not|don\'t|require|unless|except|at most|at least|'
                 r'only if|confirm|verify|authenticate|transfer|escalat)\b', re.I)


def units(text, min_len=25, max_len=700):
    """Rule units: lines/bullets/sentences."""
    out = []
    for line in re.split(r'\n+', text):
        line = line.strip(' \t-*•#')
        if len(line) < min_len:
            continue
        if len(line) <= max_len:
            out.append(line)
        else:
            for s in re.split(r'(?<=[.!?;])\s+', line):
                if len(s) >= min_len:
                    out.append(s[:max_len])
    return out


def feats(t):
    t = t.lower()
    w = WORD.findall(t)
    f = Counter(w)
    f.update(a + ' ' + b for a, b in zip(w, w[1:]))
    s = re.sub(r'\s+', ' ', t)
    f.update('c:' + s[i:i + 4] for i in range(0, max(len(s) - 3, 0)))
    return f


def rank(policy_text, query, k=8):
    us = units(policy_text)
    if not us:
        return []
    fs = [feats(u) for u in us]
    df = Counter(x for f in fs for x in f)
    n = len(us)
    idf = lambda x: math.log((n + 1) / (df.get(x, 0) + 1)) + 1
    q = feats(query)
    qv = {x: c * idf(x) for x, c in q.items()}
    qn = math.sqrt(sum(v * v for v in qv.values())) or 1
    sc = []
    for u, f in zip(us, fs):
        dv = {x: c * idf(x) for x, c in f.items()}
        dn = math.sqrt(sum(v * v for v in dv.values())) or 1
        dot = sum(v * dv.get(x, 0) for x, v in qv.items())
        sc.append(dot / (qn * dn) + (0.03 if CUE.search(u) else 0))
    order = sorted(range(n), key=lambda i: -sc[i])[:k]
    return [us[i] for i in sorted(order)]


def move_text(packet):
    return ' '.join((t.get('tool') or '') + ' ' + (t.get('text') or '') for t in packet.get('current_targets', []))

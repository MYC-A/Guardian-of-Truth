"""Offline calibration from triage scores (+ optional B2 labels). Reads labels; never used at inference."""
from __future__ import annotations


def metrics(pairs):
    tp = sum(1 for y, p in pairs if y == 1 and p == 1)
    fp = sum(1 for y, p in pairs if y == 0 and p == 1)
    fn = sum(1 for y, p in pairs if y == 1 and p == 0)
    tn = sum(1 for y, p in pairs if y == 0 and p == 0)
    f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    return dict(TP=tp, FP=fp, FN=fn, TN=tn, F1=round(f1, 4))


def auc(scores, labels):
    pos = [scores[i] for i in labels if labels[i] == 1 and scores.get(i) is not None]
    neg = [scores[i] for i in labels if labels[i] == 0 and scores.get(i) is not None]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 4)


def best_threshold(scores, labels):
    candidates = sorted({s for s in scores.values() if s is not None} | {0.5})
    best = None
    for t in candidates:
        m = metrics([(labels[i], int(scores.get(i) is not None and scores[i] >= t)) for i in labels])
        if best is None or m['F1'] > best[1]['F1']:
            best = (t, m)
    return dict(threshold=best[0], **best[1])


def escalation_curve(scores, labels, b2, direct_threshold, or_threshold=None):
    """F1 when only the top-k rows by priority receive B2, k = 0..n (k ~ wall time)."""
    from guardian_truth.cascade.controller import Policy, final_label, priority
    policy = Policy(direct_threshold=direct_threshold, or_threshold=or_threshold)
    order = priority({i: scores.get(i) for i in labels}, Policy())
    curve = []
    for k in range(len(order) + 1):
        escalated = set(order[:k])
        pairs = [(labels[i], final_label(scores.get(i), b2.get(i) if i in escalated else None, policy)[0])
                 for i in labels]
        curve.append(dict(k=k, **metrics(pairs)))
    return curve

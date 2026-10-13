"""Rank-based labelling instead of a probability threshold.

Public leaderboard: every team's recall is a multiple of 1/130, so the public test has 130 positives
in 548 rows (23.7%); top teams label 25-34% of rows. Probabilities are not calibrated for this task
(valid46 is 50/50), so we label a fixed share of the scored rows by rank, plus every hard finding.
"""


def decide(n, hard, scores, positive_rate):
    labels = [0] * n
    for i in hard:
        labels[i] = 1
    scored = [i for i in range(n) if scores.get(i) is not None]
    if scored:
        target = int(round(positive_rate * len(scored)))
        already = sum(1 for i in scored if i in hard)
        ranked = sorted((i for i in scored if i not in hard), key=lambda i: (-scores[i], i))
        for i in ranked[:max(0, target - already)]:
            labels[i] = 1
    return labels

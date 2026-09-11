"""Dependency-free paired statistics for frozen Guardian experiments."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Callable


def binary_metrics(labels: list[int], predictions: list[int]) -> dict[str, float | int]:
    if len(labels) != len(predictions) or any(v not in (0, 1) for v in labels + predictions):
        raise ValueError("binary aligned inputs required")
    tp = sum(y == p == 1 for y, p in zip(labels, predictions))
    tn = sum(y == p == 0 for y, p in zip(labels, predictions))
    fp = sum(y == 0 and p == 1 for y, p in zip(labels, predictions))
    fn = sum(y == 1 and p == 0 for y, p in zip(labels, predictions))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"n": len(labels), "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "accuracy": (tp + tn) / len(labels) if labels else 0.0,
            "fpr": fp / (fp + tn) if fp + tn else 0.0}


def mcnemar_exact(labels: list[int], incumbent: list[int], candidate: list[int]) -> dict[str, float | int]:
    if not (len(labels) == len(incumbent) == len(candidate)):
        raise ValueError("aligned inputs required")
    incumbent_only = sum(a == y and b != y for y, a, b in zip(labels, incumbent, candidate))
    candidate_only = sum(b == y and a != y for y, a, b in zip(labels, incumbent, candidate))
    discordant = incumbent_only + candidate_only
    if not discordant:
        p_value = 1.0
    else:
        tail = sum(math.comb(discordant, k) for k in range(min(incumbent_only, candidate_only) + 1))
        p_value = min(1.0, 2.0 * tail / (2 ** discordant))
    return {"incumbent_only_correct": incumbent_only,
            "candidate_only_correct": candidate_only,
            "discordant": discordant, "p_value_two_sided": p_value}


def hierarchical_bootstrap_delta(
    labels: list[int], incumbent: list[int], candidate: list[int], groups: list[str],
    *, metric: Callable[[list[int], list[int]], float] | None = None,
    samples: int = 2000, seed: int = 0,
) -> dict[str, float | int]:
    if not (len(labels) == len(incumbent) == len(candidate) == len(groups)) or not labels:
        raise ValueError("non-empty aligned inputs required")
    if samples <= 0:
        raise ValueError("samples must be positive")
    metric = metric or (lambda y, p: float(binary_metrics(y, p)["f1"]))
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        grouped[str(group)].append(index)
    keys = sorted(grouped)
    rng = random.Random(seed)
    deltas = []
    for _ in range(samples):
        indices: list[int] = []
        for group in (rng.choice(keys) for _ in keys):
            members = grouped[group]
            indices.extend(rng.choice(members) for _ in members)
        y = [labels[i] for i in indices]
        a = [incumbent[i] for i in indices]
        b = [candidate[i] for i in indices]
        deltas.append(metric(y, b) - metric(y, a))
    deltas.sort()
    lower = deltas[int(0.025 * (samples - 1))]
    upper = deltas[int(0.975 * (samples - 1))]
    point = metric(labels, candidate) - metric(labels, incumbent)
    return {"samples": samples, "seed": seed, "point_delta": point,
            "ci95_low": lower, "ci95_high": upper}


def calibration_metrics(labels: list[int], scores: list[float], *, bins: int = 10) -> dict[str, float]:
    if len(labels) != len(scores) or not labels or bins <= 0:
        raise ValueError("non-empty aligned inputs required")
    if any(y not in (0, 1) for y in labels) or any(not 0 <= s <= 1 for s in scores):
        raise ValueError("labels/scores outside range")
    brier = sum((score - label) ** 2 for label, score in zip(labels, scores)) / len(labels)
    buckets = [[] for _ in range(bins)]
    for label, score in zip(labels, scores):
        buckets[min(bins - 1, int(score * bins))].append((label, score))
    ece = 0.0
    for bucket in buckets:
        if bucket:
            confidence = sum(score for _, score in bucket) / len(bucket)
            accuracy = sum(label for label, _ in bucket) / len(bucket)
            ece += len(bucket) / len(labels) * abs(confidence - accuracy)
    return {"brier": brier, "ece": ece}

"""Offline, provenance-grouped evaluation. Labels never enter a detector call."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping


SPLITS = ('train', 'calibration', 'test')
GROUP_FIELDS = ('group_id', 'source_id', 'dialogue_id', 'template_id', 'pair_id')
LIMITATIONS = [
    'Synthetic mechanism tests are not an independent natural competition test.',
    'Finite samples and few independent provenance groups can yield unstable or degenerate intervals.',
    'Group bootstrap intervals condition on this sample and do not establish robustness to distribution shift.',
    'Exact and whitespace-normalized duplicate checks do not detect all semantic near-duplicates.',
    'A detector score of zero or fallback label zero is not a proof that a response is correct.',
]


@dataclass(frozen=True)
class Example:
    id: str
    prompt: str
    response: str
    label: int
    group_id: str = ''
    source_id: str = ''
    dialogue_id: str = ''
    template_id: str = ''
    pair_id: str = ''
    split: str = ''
    family: str = ''
    synthetic: bool = False
    component: str = ''


@dataclass(frozen=True)
class Score:
    id: str
    score: float
    status: str = ''
    fixed_label: int | None = None


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def load_examples(path: str | Path) -> list[Example]:
    """Read labelled CSV/JSONL; require at least one explicit provenance key."""
    path = Path(path)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        if path.suffix.lower() == '.jsonl':
            rows = [json.loads(line) for line in stream if line.strip()]
        elif path.suffix.lower() == '.csv':
            rows = list(csv.DictReader(stream))
        else:
            raise ValueError('Input must be .jsonl or .csv')
    examples = []
    for row in rows:
        if not isinstance(row, dict) or any(k not in row for k in ('id', 'prompt', 'response', 'label')):
            raise ValueError('Required fields: id, prompt, response, label')
        if str(row['label']) not in ('0', '1'):
            raise ValueError('Labels must be 0 or 1')
        synthetic = row.get('synthetic', False)
        if str(synthetic).lower() not in ('true', 'false', '0', '1', ''):
            raise ValueError('synthetic must be boolean')
        values = {k: row.get(k, '') for k in GROUP_FIELDS + ('split', 'family')}
        if not all(isinstance(v, str) for v in values.values()):
            raise ValueError('Group, split and family fields must be strings')
        examples.append(Example(str(row['id']), row['prompt'], row['response'], int(row['label']),
                                **values, synthetic=str(synthetic).lower() in ('true', '1')))
    return prepare_examples(examples)[0]


def prepare_examples(examples: Iterable[Example]) -> tuple[list[Example], dict]:
    """Union all shared provenance keys and duplicate inputs, including transitive links.

    Keys are global within their field, so callers must namespace unrelated corpora.
    Conflicting labels on identical normalized input are rejected. Cross-split links
    are rejected even when they only arise through a chain of different key fields.
    """
    examples = list(examples)
    if not examples:
        raise ValueError('Dataset is empty')
    parents = list(range(len(examples)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    def union(i, j):
        a, b = root(i), root(j)
        parents[max(a, b)] = min(a, b)

    ids, seen, exact, normalized = set(), {}, {}, {}
    duplicates = []
    for i, example in enumerate(examples):
        if not example.id or example.id in ids:
            raise ValueError(f'Empty or duplicate id: {example.id}')
        ids.add(example.id)
        if type(example.label) is not int or example.label not in (0, 1):
            raise ValueError('Labels must be integer 0 or 1')
        if not isinstance(example.prompt, str) or not isinstance(example.response, str):
            raise ValueError('prompt and response must be strings')
        if example.split and example.split not in SPLITS:
            raise ValueError(f'Invalid split: {example.split}')
        if not any(getattr(example, field) for field in GROUP_FIELDS):
            raise ValueError(f'Explicit provenance/group metadata required: {example.id}')
        for field in GROUP_FIELDS:
            value = getattr(example, field)
            if not value:
                continue
            key = (field, value)
            if key in seen:
                union(i, seen[key])
            else:
                seen[key] = i
        raw_key = _hash([example.prompt, example.response])
        norm_key = _hash([' '.join(example.prompt.split()), ' '.join(example.response.split())])
        for index, key, kind in ((exact, raw_key, 'exact'), (normalized, norm_key, 'whitespace')):
            if key in index:
                previous = index[key]
                if example.label != examples[previous].label:
                    raise ValueError(f'Conflicting duplicate labels: {examples[previous].id}, {example.id}')
                union(i, previous)
                if kind == 'exact' or raw_key != _hash([examples[previous].prompt, examples[previous].response]):
                    duplicates.append({'first': examples[previous].id, 'second': example.id, 'kind': kind})
            else:
                index[key] = i
    members = {}
    for i in range(len(examples)):
        members.setdefault(root(i), []).append(i)
    components = {}
    for component, indices in members.items():
        assigned = {examples[i].split for i in indices if examples[i].split}
        if len(assigned) > 1:
            raise ValueError('Group/duplicate leakage across explicit splits: ' +
                             ', '.join(examples[i].id for i in indices))
        components[component] = _hash(sorted(examples[i].id for i in indices))[:24]
    prepared = [replace(example, component=components[root(i)]) for i, example in enumerate(examples)]
    return prepared, {'rows': len(prepared), 'groups': len(members), 'duplicates': duplicates}


def split_examples(examples: Iterable[Example], *, seed: int = 0,
                   fractions=(0.6, 0.2, 0.2)) -> list[Example]:
    """Deterministically assign whole components; never override explicit splits.

    Hash assignment is independent of labels/order. Small datasets may have empty
    splits: no post-hoc movement of groups or label balancing hides that limitation.
    """
    if len(fractions) != 3 or any(not math.isfinite(f) or f < 0 for f in fractions) or not math.isclose(sum(fractions), 1):
        raise ValueError('Three nonnegative finite fractions must sum to one')
    examples, _ = prepare_examples(examples)
    assignments = {e.component: e.split for e in examples if e.split}
    for example in examples:
        if example.component not in assignments:
            value = int(_hash([seed, example.component])[:16], 16) / 2**64
            assignments[example.component] = (SPLITS[0] if value < fractions[0] else
                                               SPLITS[1] if value < sum(fractions[:2]) else SPLITS[2])
    return [replace(e, split=assignments[e.component]) for e in examples]


def score_examples(examples: Iterable[Example], detector, *, use_semantic: bool = False) -> list[Score]:
    """Only prompt/response enter detector.review (or a two-string callable).

    Hard violation fixes the label at 1; explicitly enabled semantic_score is
    thresholded; otherwise unknown fixes the fallback label at 0. Semantic scores
    and fallback scores are operational scores, not calibrated probabilities.
    A callable can return a float directly, enabling reusable model evaluation.
    """
    scores = []
    for example in examples:
        result = (detector.review(example.prompt, example.response) if hasattr(detector, 'review')
                  else detector(example.prompt, example.response))
        if isinstance(result, (int, float)):
            value, status, fixed_label = float(result), '', None
        else:
            status = result.status
            value = 1.0 if status == 'violation' else None
            fixed_label = 1 if status == 'violation' else None
            if value is None and use_semantic:
                value = getattr(result, 'semantic_score', None)
            if value is None:
                value, fixed_label = 0.0, 0
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f'Invalid score for {example.id}: {value}')
        scores.append(Score(example.id, float(value), status, fixed_label))
    return scores


def _aligned(examples, scores):
    scores = list(scores)
    index = {s.id: s.score for s in scores}
    if len(index) != len(scores) or set(index) != {e.id for e in examples}:
        raise ValueError('Scores must contain every example ID exactly once, with no extras')
    if any(not math.isfinite(s) or not 0 <= s <= 1 for s in index.values()):
        raise ValueError('Scores must be finite and in [0, 1]')
    if any(s.fixed_label is not None and (type(s.fixed_label) is not int or s.fixed_label not in (0, 1))
           for s in scores):
        raise ValueError('Fixed labels must be integer 0, 1, or None')
    return [index[e.id] for e in examples]


def _predictions(examples, scores, threshold):
    scores = list(scores)
    values = _aligned(examples, scores)
    index = {score.id: score for score in scores}
    return [1 if index[e.id].status == 'violation' else
            index[e.id].fixed_label if index[e.id].fixed_label is not None else int(value >= threshold)
            for e, value in zip(examples, values)]


def metrics(labels, predictions) -> dict:
    labels, predictions = list(labels), list(predictions)
    if not labels or len(labels) != len(predictions):
        raise ValueError('Equal, nonempty labels and predictions required')
    if any(type(v) is not int or v not in (0, 1) for v in labels + predictions):
        raise ValueError('Labels and predictions must be integer 0 or 1')
    tp = sum(y == p == 1 for y, p in zip(labels, predictions))
    fp = sum(y == 0 and p == 1 for y, p in zip(labels, predictions))
    fn = sum(y == 1 and p == 0 for y, p in zip(labels, predictions))
    tn = len(labels) - tp - fp - fn
    return {'n': len(labels), 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
            'precision': tp / (tp + fp) if tp + fp else 0.0,
            'recall': tp / (tp + fn) if tp + fn else 0.0,
            'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0}


def select_threshold(examples: Iterable[Example], scores: Iterable[Score]) -> dict:
    """Choose maximum calibration F1. Reject ANY train/test row supplied.

    Ties prefer precision, then the higher threshold. Candidates stay in [0, 1]
    to match the production decision interface; fixed decisions are preserved.
    """
    examples, _ = prepare_examples(examples)
    if any(e.split != 'calibration' for e in examples):
        raise ValueError('Threshold selection requires exclusively explicit calibration rows')
    scores = list(scores)
    values = _aligned(examples, scores)
    unique = sorted(set(values))
    candidates = sorted({0.0, 0.5, 1.0, *unique,
                         *((a + b) / 2 for a, b in zip(unique, unique[1:]))})
    evaluated = [(metrics([e.label for e in examples], _predictions(examples, scores, t)), t)
                 for t in candidates]
    best, threshold = max(evaluated, key=lambda item: (item[0]['f1'], item[0]['precision'], item[1]))
    return {'threshold': threshold, 'selection_split': 'calibration', 'objective': 'f1',
            'tie_break': 'precision_then_higher_threshold', 'metrics': best,
            'calibration_ids_hash': _hash(sorted(e.id for e in examples))}


def paired_comparison(examples: Iterable[Example], baseline: Iterable[Score], candidate: Iterable[Score], *,
                      baseline_threshold: float = 0.5, candidate_threshold: float = 0.5,
                      bootstrap_samples: int = 1000, seed: int = 0) -> dict:
    """Paired cluster bootstrap: resample provenance components, both systems together."""
    examples, audit = prepare_examples(examples)
    if bootstrap_samples < 1:
        raise ValueError('bootstrap_samples must be positive')
    if not all(math.isfinite(t) and 0 <= t <= 1 for t in (baseline_threshold, candidate_threshold)):
        raise ValueError('Thresholds must be finite and in [0, 1]')
    a = _predictions(examples, baseline, baseline_threshold)
    b = _predictions(examples, candidate, candidate_threshold)
    labels = [e.label for e in examples]
    before, after = metrics(labels, a), metrics(labels, b)
    metric_names = ('f1', 'precision', 'recall')
    groups = {}
    for i, example in enumerate(examples):
        groups.setdefault(example.component, []).append(i)
    clusters = [groups[key] for key in sorted(groups)]
    rng = random.Random(seed)
    differences = {key: [] for key in metric_names}
    for _ in range(bootstrap_samples):
        indices = [i for _ in clusters for i in rng.choice(clusters)]
        ma = metrics([labels[i] for i in indices], [a[i] for i in indices])
        mb = metrics([labels[i] for i in indices], [b[i] for i in indices])
        for key in metric_names:
            differences[key].append(mb[key] - ma[key])

    def percentile(values, q):
        ordered = sorted(values)
        position = (len(ordered) - 1) * q
        lo, hi = math.floor(position), math.ceil(position)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)

    return {'baseline': before, 'candidate': after,
            'delta': {key: after[key] - before[key] for key in metric_names},
            'changes': {'changed': sum(x != y for x, y in zip(a, b)),
                        'zero_to_one': sum(x == 0 and y == 1 for x, y in zip(a, b)),
                        'one_to_zero': sum(x == 1 and y == 0 for x, y in zip(a, b)),
                        'corrected': sum(x != y and y == label for x, y, label in zip(a, b, labels)),
                        'regressed': sum(x == label and y != label for x, y, label in zip(a, b, labels))},
            'uncertainty': {'method': 'paired_provenance_group_percentile_bootstrap',
                            'confidence': 0.95, 'replicates': bootstrap_samples, 'seed': seed,
                            'groups': len(clusters), 'delta_intervals': {
                                key: [percentile(values, .025), percentile(values, .975)]
                                for key, values in differences.items()}},
            'duplicate_audit': audit, 'zero_denominator_convention': 0.0,
            'limitations': LIMITATIONS + (['Fewer than 20 independent groups; intervals need particular caution.']
                                          if len(clusters) < 20 else [])}


def frozen_manifest(examples: Iterable[Example], configuration: Mapping[str, Any]) -> dict:
    """Return a detached configuration and content hashes to freeze before test scoring."""
    examples, audit = prepare_examples(examples)
    configuration = json.loads(json.dumps(configuration, allow_nan=False))
    rows = sorted((asdict(e) for e in examples), key=lambda row: row['id'])
    content = {'version': 1, 'configuration': configuration, 'dataset_hash': _hash(rows),
               'configuration_hash': _hash(configuration), 'rows': len(rows), 'groups': audit['groups'],
               'membership': [{'id': e.id, 'split': e.split, 'component': e.component}
                              for e in sorted(examples, key=lambda e: e.id)]}
    return {**content, 'manifest_hash': _hash(content)}


def verify_manifest(manifest: Mapping[str, Any]) -> bool:
    content = dict(manifest)
    expected = content.pop('manifest_hash', None)
    return expected == _hash(content) and content.get('configuration_hash') == _hash(content.get('configuration'))


def run_benchmark(examples: Iterable[Example], baseline, candidate, *, configuration: Mapping[str, Any],
                  calibrate: bool = False, baseline_threshold: float = 0.5,
                  candidate_threshold: float = 0.5, baseline_use_semantic: bool = False,
                  candidate_use_semantic: bool = False,
                  bootstrap_samples: int = 1000, seed: int = 0, on_frozen=None) -> dict:
    """Score calibration, freeze config, then score test. Train rows are never scored.

    Caller configuration must identify both systems, model/prompt revisions, and
    decoding settings when relevant. This harness cannot prevent outside tuning.
    """
    if type(bootstrap_samples) is not int or bootstrap_samples < 1:
        raise ValueError('bootstrap_samples must be a positive integer')
    if not all(type(t) in (int, float) and math.isfinite(t) and 0 <= t <= 1
               for t in (baseline_threshold, candidate_threshold)):
        raise ValueError('Thresholds must be finite and in [0, 1]')
    examples, audit = prepare_examples(examples)
    if any(not e.split for e in examples):
        raise ValueError('Every row needs an explicit split; call split_examples first if desired')
    calibration = [e for e in examples if e.split == 'calibration']
    test = [e for e in examples if e.split == 'test']
    if not test:
        raise ValueError('No test examples')
    selection = None
    if calibrate:
        if not calibration:
            raise ValueError('Calibration split is required to select thresholds')
        selection = {'baseline': select_threshold(calibration, score_examples(calibration, baseline, use_semantic=baseline_use_semantic)),
                     'candidate': select_threshold(calibration, score_examples(calibration, candidate, use_semantic=candidate_use_semantic))}
        baseline_threshold = selection['baseline']['threshold']
        candidate_threshold = selection['candidate']['threshold']
    config = {**dict(configuration), 'baseline_threshold': baseline_threshold,
              'candidate_threshold': candidate_threshold, 'threshold_selection': selection,
              'bootstrap_samples': bootstrap_samples, 'seed': seed,
              'baseline_use_semantic': baseline_use_semantic, 'candidate_use_semantic': candidate_use_semantic,
              'score_mapping': 'hard_violation_fixed_1_else_explicit_raw_semantic_else_unknown_fixed_0',
              'hard_violation_override': True}
    manifest = frozen_manifest(examples, config)
    if on_frozen is not None:
        # Give the persistence hook a detached value before ANY test inference.
        # A failed write aborts the run rather than leaving an unrecorded test.
        on_frozen(json.loads(json.dumps(manifest, allow_nan=False)))
    first = score_examples(test, baseline, use_semantic=baseline_use_semantic)
    second = score_examples(test, candidate, use_semantic=candidate_use_semantic)
    report = paired_comparison(test, first, second, baseline_threshold=baseline_threshold,
                               candidate_threshold=candidate_threshold,
                               bootstrap_samples=bootstrap_samples, seed=seed)
    first_predictions = _predictions(test, first, baseline_threshold)
    second_predictions = _predictions(test, second, candidate_threshold)
    per_example = [{'id': e.id, 'split': e.split, 'component': e.component, 'label': e.label,
                    'family': e.family, 'synthetic': e.synthetic,
                    'baseline_score': a.score, 'candidate_score': b.score,
                    'baseline_prediction': ap, 'candidate_prediction': bp,
                    'baseline_status': a.status, 'candidate_status': b.status,
                    'baseline_fixed_label': a.fixed_label, 'candidate_fixed_label': b.fixed_label}
                   for e, a, b, ap, bp in zip(test, first, second, first_predictions, second_predictions)]
    return {'manifest': manifest, 'report': report, 'per_example': per_example,
            'dataset_audit': audit, 'test_kind': 'synthetic_mechanism_test' if all(e.synthetic for e in test)
            else 'user_supplied_test_independence_not_established'}


class ActiveClock:
    """Serial evaluation clock: exclude time spent running the other detector.

    Production inference retains a wall-clock budget. Use this clock only inside
    measure() around each complete review; network waits and retries count too.
    It is intentionally not a concurrent scheduler.
    """

    def __init__(self, clock=None):
        self.clock = clock or time.monotonic
        self.elapsed = 0.0
        self.started = None

    def __call__(self):
        return self.elapsed + (self.clock()-self.started if self.started is not None else 0.0)

    @contextmanager
    def measure(self):
        if self.started is not None:
            raise RuntimeError('ActiveClock cannot have overlapping measurements')
        self.started = self.clock()
        try:
            yield
        finally:
            self.elapsed += self.clock()-self.started
            self.started = None

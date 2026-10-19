"""Local evaluation of the single-pass judge on a labelled file. Labels are used only for scoring.

Runs the submission pieces unchanged: mechanical layer -> scripts/judge_stage.py subprocess -> scores.
Reports AUC (threshold-free; the model-selection metric), F1 when a fixed share of rows is labelled 1,
mechanical findings per gold label, exactness of the scores, time and throughput.

  # CPU only: which hard checks fire on label-0 rows (must be zero)
  python scripts/eval_judge_valid.py --input valid.parquet --mechanical-only --out runs/mech
  # model comparison
  python scripts/eval_judge_valid.py --input valid.parquet --model models/qwen36-a3b-awq --out runs/q36
  # pessimistic speed test: N unique rows (unique prefix disables cross-row cache reuse),
  # with the real 23-minute stop rule measured from the start of this script
  python scripts/eval_judge_valid.py --input valid.parquet --model models/qwen36-a3b-awq \
      --timing-rows 560 --seconds 1380 --out runs/q36_timing

With the bundled runtime pass --python <archive>/runtime/python/run_python.sh.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / 'src')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from guardian_truth.judge.decision import decide  # noqa: E402
from guardian_truth.judge.mechanical import analyze  # noqa: E402
from scripts.judge_submission import (effective_scores, load_config, read_input, read_question_scores,
                                     read_review_scores, read_scores)  # noqa: E402
from guardian_truth.judge.blind_review import effective_for_eval  # noqa: E402


def read_labels(path, n):
    import pandas as pd
    path = Path(path)
    with path.open('rb') as stream:
        parquet = stream.read(4) == b'PAR1'
    frame = pd.read_parquet(path) if parquet else pd.read_csv(path)
    if 'label' not in frame.columns or len(frame) != n:
        return None
    return [int(v) for v in frame['label']]


def read_labels_sidecar(path, rows):
    """Gold-only JSONL, aligned by position AND literal id; never passed to the stage."""
    records = [json.loads(line) for line in Path(path).read_bytes().split(b'\n') if line.strip()]
    if len(records) != len(rows):
        raise ValueError('LABEL_SIDECAR_LENGTH')
    result = []
    for position, (record, row) in enumerate(zip(records, rows)):
        if type(record.get('position')) is not int or record['position'] != position or record.get('id') != row['id']:
            raise ValueError('LABEL_SIDECAR_POSITION_ID')
        if type(record.get('label')) is not int or record['label'] not in (0, 1):
            raise ValueError('LABEL_SIDECAR_BINARY')
        if record.get('source_pair_sha256') is not None:
            raw = json.dumps([row['prompt'], row['response']], ensure_ascii=False,
                             sort_keys=True, separators=(',', ':')).encode('utf-8')
            if hashlib.sha256(raw).hexdigest() != record['source_pair_sha256']:
                raise ValueError('LABEL_SIDECAR_SOURCE_PAIR')
        result.append(record['label'])
    return result


def auc(labels, scores):
    pos = [s for y, s in zip(labels, scores) if y == 1]
    neg = [s for y, s in zip(labels, scores) if y == 0]
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > q else 0.5 if p == q else 0.0 for p in pos for q in neg)
    return round(wins / (len(pos) * len(neg)), 4)


def confusion(labels, preds):
    tp = sum(1 for y, p in zip(labels, preds) if y == 1 and p == 1)
    fp = sum(1 for y, p in zip(labels, preds) if y == 0 and p == 1)
    fn = sum(1 for y, p in zip(labels, preds) if y == 1 and p == 0)
    f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    return dict(tp=tp, fp=fp, fn=fn, tn=len(labels) - tp - fp - fn, f1=round(f1, 4),
                precision=round(tp / (tp + fp), 4) if tp + fp else 0.0,
                recall=round(tp / (tp + fn), 4) if tp + fn else 0.0)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--labels-file', type=Path, help='gold-only positional JSONL; labels stay outside model input')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--model', type=Path)
    ap.add_argument('--config', type=Path, default=ROOT / 'submission/JUDGE_CONFIG.json')
    ap.add_argument('--python', default=sys.executable)
    ap.add_argument('--seconds', type=float, default=3600, help='stop rule for the stage, from script start')
    ap.add_argument('--timing-rows', type=int, default=0)
    ap.add_argument('--rates', default='0.25,0.30,0.35,0.40,0.50')
    ap.add_argument('--mechanical-only', action='store_true')
    ap.add_argument('--exploratory-thresholds', action='store_true',
                    help='report optimistic in-sample threshold diagnostics; never a promotion criterion')
    a = ap.parse_args(argv)
    started = time.time()
    a.out.mkdir(parents=True, exist_ok=False)
    cfg = load_config(ROOT, a.config)
    rows = read_input(a.input)
    labels = read_labels_sidecar(a.labels_file, rows) if a.labels_file else read_labels(a.input, len(rows))
    if a.timing_rows:
        base = rows
        rows = [dict(base[k % len(base)], prompt='[timing row %d]\n' % k + base[k % len(base)]['prompt'])
                for k in range(a.timing_rows)]
        labels = None
    n = len(rows)
    t0 = time.time()
    findings = [analyze(r['prompt'], r['response'], bool(cfg['hard_unknown_identifier']),
                        bounded_turn_shape=bool(cfg.get('bounded_turn_shape',False))) for r in rows]
    summary = dict(rows=n, mechanical_seconds=round(time.time() - t0, 2),
                   hard_rows=sum(1 for f in findings if f.hard),
                   rows_with_hints=sum(1 for f in findings if f.hints))
    if a.labels_file:
        summary['labels_sidecar_sha256'] = hashlib.sha256(a.labels_file.read_bytes()).hexdigest()
        summary['input_file_sha256'] = hashlib.sha256(a.input.read_bytes()).hexdigest()
    if labels:
        by_kind = {}
        for f, y in zip(findings, labels):
            for item in f.hard:
                kind = item.split()[0]
                by_kind.setdefault(kind, {'label1': 0, 'label0': 0})['label%d' % y] += 1
        summary['hard_by_kind'] = by_kind
        summary['hard_rows_on_label0'] = sum(1 for f, y in zip(findings, labels) if f.hard and y == 0)
        summary['hard_rows_on_label1'] = sum(1 for f, y in zip(findings, labels) if f.hard and y == 1)
        summary['hard_on_label0_details'] = [dict(id=r['id'], hard=f.hard)
                                             for r, f, y in zip(rows, findings, labels) if f.hard and y == 0]
    scores, primary_scores, review_scores = {}, {}, {}
    if not a.mechanical_only:
        if a.model is None:
            raise SystemExit('--model is required unless --mechanical-only')
        stage_input = a.out / 'stage_input.jsonl'
        with stage_input.open('w', encoding='utf-8') as stream:
            for i, (row, f) in enumerate(zip(rows, findings)):
                stream.write(json.dumps(dict(key=i, prompt=row['prompt'], response=row['response'],
                                             hints=f.hints), ensure_ascii=False) + '\n')
        stage_config = a.out / 'judge_config.json'
        stage_config.write_text(json.dumps(cfg), encoding='utf-8')
        scores_path = a.out / 'scores.jsonl'
        env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', VLLM_NO_USAGE_STATS='1')
        if str(a.python).endswith('run_python.sh'):
            for key in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD'):
                env.pop(key, None)
        command = [str(a.python), str(ROOT / 'scripts/judge_stage.py'), '--model', str(a.model),
                   '--input', str(stage_input), '--output', str(scores_path), '--config', str(stage_config),
                   '--stop-at', repr(started + a.seconds)]
        t1 = time.time()
        with (a.out / 'stage.log').open('w', encoding='utf-8') as log:
            code = subprocess.call(command, stdout=log, stderr=subprocess.STDOUT, env=env)
        summary['stage_exit'] = code
        summary['stage_wall_seconds'] = round(time.time() - t1, 1)
        summary['total_wall_seconds'] = round(time.time() - started, 1)
        partial_review = cfg.get('review_ranking') == 'max_exact'
        scores, missing, inexact, events = read_scores(scores_path, exact_only=(
            cfg.get('aggregate') == 'max_logit' or partial_review))
        summary.update(scored=len(scores), no_score=missing, inexact=inexact,
                       **{'stage_' + k: v for k, v in events.items()})
        # Apply the same aggregate and review selection as the actual supervisor.
        primary_scores, review_scores = scores, read_review_scores(scores_path, isolate_duplicates=partial_review)
        question = read_question_scores(scores_path)
        aggregated, aggregate_ranking, aggregate_lacking = effective_scores(
            primary_scores, question, cfg, [f.features for f in findings])
        scores, ranking, lacking = effective_for_eval(cfg, aggregated, review_scores, n)
        if cfg.get('review_mode', 'off') == 'off':
            ranking, lacking = aggregate_ranking, aggregate_lacking
        summary['ranking'] = ranking
        summary['ranked_rows'] = len(scores)
        summary['aggregate_lacking_rows'] = aggregate_lacking
        summary['question_coverage'] = {
            key: sum(key in v for v in question.values()) for key in cfg.get('aggregate_keys', [])}
        if cfg.get('review_mode', 'off') != 'off':
            common = [i for i in range(n) if i in primary_scores and i in review_scores]
            summary['review'] = dict(arm=cfg['review_mode'], rows_without_final=lacking,
                                     final_scored=len(review_scores), exact_intersection=len(common))
            if labels and common:
                summary['review'].update(
                    auc_primary_intersection=auc([labels[i] for i in common], [primary_scores[i] for i in common]),
                    auc_final_intersection=auc([labels[i] for i in common], [review_scores[i] for i in common]))
        if labels and scores:
            idx = [i for i in range(n) if i in scores]
            summary['auc_judge'] = auc([labels[i] for i in idx], [scores[i] for i in idx])
            combined = [1e9 if findings[i].hard else scores[i] for i in idx]
            summary['auc_with_mechanical'] = auc([labels[i] for i in idx], combined)
            hard = {i for i, f in enumerate(findings) if f.hard}
            summary['f1_at_rate'] = {rate: confusion(labels, decide(n, hard, scores, float(rate)))
                                     for rate in a.rates.split(',')}
            if a.exploratory_thresholds:
                candidates = [(confusion(labels, [1 if (i in hard or scores.get(i, float('-inf')) >= t) else 0
                                                  for i in range(n)]), t) for t in sorted(set(scores.values()))]
                best, threshold = max(candidates, key=lambda item: item[0]['f1'])
                summary['best_threshold_in_sample'] = dict(best, threshold=threshold,
                                                            note='selected on the same rows: optimistic')
    with (a.out / 'rows.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['index', 'id', 'label', 'score', 'primary_score', 'final_score', 'hard', 'hints'])
        for i, (row, f) in enumerate(zip(rows, findings)):
            writer.writerow([i, row['id'], '' if labels is None else labels[i], scores.get(i, ''),
                             primary_scores.get(i, ''), review_scores.get(i, ''),
                             ' | '.join(f.hard), ' | '.join(f.hints)])
    (a.out / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str),
                                        encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'hard_on_label0_details'},
                     indent=2, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()

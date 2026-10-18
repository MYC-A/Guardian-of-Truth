"""Gold-side analysis of a complete frozen-generation final replay; no model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from guardian_truth.judge.decision import decide
from guardian_truth.judge.mechanical import analyze
from scripts.analyze_judge_dependencies_20261018 import metrics, rank_metrics
from scripts.analyze_judge_gpu_run_20261018 import finite, paired_ci
from scripts.eval_judge_valid import read_labels_sidecar
from scripts.judge_submission import read_input
from scripts.replay_judge_notes_20261018 import ARMS, close_source, read


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--replay', type=Path, required=True)
    p.add_argument('--source-run', type=Path, required=True)
    p.add_argument('--inputs', type=Path, required=True)
    p.add_argument('--labels-file', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    done = json.loads((a.replay / 'DONE.json').read_bytes())
    for name, expected in done['source_files_sha256'].items():
        if hashlib.sha256((a.source_run / name).read_bytes()).hexdigest() != expected:
            raise ValueError('REPLAY_SOURCE_RECEIPT_CHANGED')
    cfg, _, _, old_final, _, _ = close_source(a.source_run)
    rows = read_input(a.inputs)
    labels = read_labels_sidecar(a.labels_file, rows)
    gold = read(a.labels_file)
    stage_input = {r['key']: r for r in read(a.source_run / 'stage_input.jsonl')}
    if len(rows) != done['rows'] or any((r['prompt'], r['response']) !=
            (stage_input[i]['prompt'], stage_input[i]['response']) for i, r in enumerate(rows)):
        raise ValueError('ANALYSIS_SOURCE_CHANGED')
    scores = {arm: {} for arm in ARMS}
    records = {}
    for r in read(a.replay / 'scores.jsonl'):
        arm, key = r['arm'], r['key']
        if arm not in scores or key in scores[arm] or r['exact'] is not True or finite(r['final_score']) is None:
            raise ValueError('INVALID_OR_DUPLICATE_REPLAY_SCORE')
        scores[arm][key] = r['final_score']
        records[arm, key] = r
    if any(set(v) != set(range(len(rows))) for v in scores.values()):
        raise ValueError('INCOMPLETE_REPLAY')
    hard = {i for i, r in enumerate(rows) if analyze(r['prompt'], r['response'], cfg['hard_unknown_identifier']).hard}

    def scope(indices):
        y = [labels[i] for i in indices]
        groups = [gold[i]['group'] for i in indices]
        methods, preds = {}, {}
        for arm in ARMS:
            values = {j: scores[arm][i] for j, i in enumerate(indices)}
            preds[arm] = {str(rate): decide(len(indices), {j for j, i in enumerate(indices) if i in hard}, values, rate)
                          for rate in (.3, .4)}
            methods[arm] = dict(f1_at_rate={rate: metrics(y, pr) for rate, pr in preds[arm].items()},
                                ranking=rank_metrics(y, [scores[arm][i] for i in indices]))
        pairs = {}
        for ref, cand in (('strict', 'partial'), ('no_notes', 'strict')):
            before, after = preds[ref]['0.4'], preds[cand]['0.4']
            pairs[cand + '_minus_' + ref] = dict(
                delta_f1=methods[cand]['f1_at_rate']['0.4']['f1'] - methods[ref]['f1_at_rate']['0.4']['f1'],
                grouped_ci=paired_ci(y, before, after, groups),
                fixed=sum(x != z and w == z for x, w, z in zip(before, after, y)),
                broken=sum(x == z and w != z for x, w, z in zip(before, after, y)))
        return dict(rows=len(indices), positive=sum(y), methods=methods, comparisons=pairs)

    report = dict(schema='guardian-note-replay-analysis-v1', all_rows=scope(list(range(len(rows)))),
                  domains={}, execution=done, generation_reused=True, independent_repeat=False,
                  verdict='EXPLORATORY_NO_AUTOMATIC_PROMOTION')
    for name, allowed in dict(external_primary={'airlines', 'healthcare'}, insurance={'insurance'}).items():
        indices = [i for i, g in enumerate(gold) if g.get('domain') in allowed]
        if indices:
            report['domains'][name] = scope(indices)
    unchanged = [i for i in range(len(rows)) if records['strict', i]['input_sha256'] == records['partial', i]['input_sha256']]
    report['numerical_diagnostics'] = dict(
        unchanged_partial_prompts=len(unchanged),
        max_score_difference_on_identical_prompts=max((abs(scores['strict'][i] - scores['partial'][i]) for i in unchanged), default=None),
        max_strict_score_difference_from_original=max(abs(scores['strict'][i] - old_final[i]['final_score']) for i in range(len(rows))))
    a.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(all_rows=report['all_rows'], numerical_diagnostics=report['numerical_diagnostics']), indent=2))


if __name__ == '__main__':
    main()

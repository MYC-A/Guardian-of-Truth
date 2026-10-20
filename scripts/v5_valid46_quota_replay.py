"""Decision-only replay of verified full-adapter scores; never starts inference."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from guardian_truth.judge.decision import decide
from scripts.v5_valid46_pipeline import metrics


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def replay(run_archive, label_archive, out):
    out.mkdir(exist_ok=False)
    run_index = json.loads(Path(str(run_archive) + '.INDEX.json').read_bytes())
    label_index = json.loads(Path(str(label_archive) + '.INDEX.json').read_bytes())
    for archive, index in [(run_archive, run_index), (label_archive, label_index)]:
        if archive.stat().st_size != index['bytes'] or digest(archive) != index['sha256']:
            raise ValueError('ARCHIVE_IDENTITY_DRIFT')
    with tarfile.open(label_archive) as tar:
        raw_labels = tar.extractfile('evaluation-input-metadata/INDEX.json').read()
        selected = [r for r in json.loads(raw_labels)['rows'] if 'valid46' in r['cohorts']]
        gold = {r['original_id']: r['label'] for r in selected}
    if len(selected) != len(gold) or len(gold) != 46:
        raise ValueError('GOLD_IDENTITY_OR_COUNT')
    result = dict(scope='valid46; decision-only quota replay; full 35B LoRA after alias repair',
        inference_rerun=False, scores_modified=False, original_quota=.4, requested_quota=.7,
        run_archive_sha256=run_index['sha256'], label_archive_sha256=label_index['sha256'],
        label_index_sha256=hashlib.sha256(raw_labels).hexdigest(), datasets_rows=46,
        gold_positives=sum(gold.values()), arms={}, production_modified=False,
        private_improvement_measured=False)
    output = []
    with tarfile.open(run_archive) as tar:
        def read(name): return json.load(tar.extractfile('pipeline/' + name))
        old = read('DONE.json')
        binding = read('adapter/ADAPTER_BINDING.json')[0]
        if not binding['complete'] or binding['covered_modules'] != 50:
            raise ValueError('FULL_ADAPTER_REQUIRED')
        for arm in ('base', 'adapter'):
            rows = [json.loads(line) for line in tar.extractfile('pipeline/' + arm + '/work/decisions.jsonl').read().splitlines()]
            if [r['key'] for r in rows] != list(range(46)) or {r['id'] for r in rows} != set(gold):
                raise ValueError('ROW_IDENTITY_OR_ORDER')
            hard = {r['key'] for r in rows if r['hard']}
            scores = {r['key']: max(r['score'], r['final_score']) for r in rows}
            if any(not math.isfinite(v) or v != rows[i]['ranked_by'] for i, v in scores.items()):
                raise ValueError('RANKING_DRIFT')
            p40 = decide(46, hard, scores, .4)
            if p40 != [r['label'] for r in rows] or metrics(rows, gold, p40) != old['metrics'][arm]:
                raise ValueError('ORIGINAL_40_REPLAY_DID_NOT_REPRODUCE')
            p70 = decide(46, hard, scores, .7)
            result['arms'][arm] = dict(hard_rows=len(hard),
                quota40=dict(metrics=metrics(rows, gold, p40), positives=sum(p40)),
                quota70=dict(metrics=metrics(rows, gold, p70), positives=sum(p70)),
                added_true_positives=sum(y == 1 and z == 0 and gold[r['id']] == 1 for r,y,z in zip(rows,p70,p40)),
                added_false_positives=sum(y == 1 and z == 0 and gold[r['id']] == 0 for r,y,z in zip(rows,p70,p40)))
            output += [dict(arm=arm, id=r['id'], label=y, gold=gold[r['id']]) for r,y in zip(rows,p70)]
    (out / 'RESULTS.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    with (out / 'predictions70.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['arm','id','label','gold']); writer.writeheader(); writer.writerows(output)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for n in ('run-archive', 'label-archive', 'out'): p.add_argument('--'+n, type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(replay(a.run_archive, a.label_archive, a.out), indent=2))

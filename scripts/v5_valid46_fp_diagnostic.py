"""Exploratory score-zero rejection after quota .70, without quota refill.

This is a frozen-score diagnostic on already inspected valid46, not a calibrated
verifier or a production candidate. No threshold search or inference is performed.
"""
import argparse
import csv
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from scripts.v5_valid46_quota_replay import replay
from scripts.v5_valid46_pipeline import metrics


def diagnostic(run_archive, label_archive, out):
    out.mkdir(exist_ok=False)
    verified = replay(run_archive, label_archive, out / 'verified_quota_replay')
    with (out / 'verified_quota_replay/predictions70.csv').open(encoding='utf-8', newline='') as stream:
        predictions = list(csv.DictReader(stream))
    result = dict(
        status='EXPLORATORY_DIAGNOSTIC_ONLY', rule='candidate70 AND (hard OR MAX_score > 0)',
        threshold=0, threshold_search=False, quota_refill=False, inference_rerun=False,
        production_modified=False, independent_validation=False,
        run_archive_sha256=verified['run_archive_sha256'],
        label_archive_sha256=verified['label_archive_sha256'], arms={})
    output = []
    with tarfile.open(run_archive) as tar:
        for arm in ('base', 'adapter'):
            rows = [json.loads(line) for line in tar.extractfile('pipeline/' + arm + '/work/decisions.jsonl').read().splitlines()]
            baseline = {r['id']: r for r in predictions if r['arm'] == arm}
            gold = {key: int(r['gold']) for key, r in baseline.items()}
            candidates = [int(baseline[r['id']]['label']) for r in rows]
            labels = [int(bool(y) and (bool(r['hard']) or r['ranked_by'] > 0)) for r, y in zip(rows, candidates)]
            if any(y > z or (r['hard'] and not y) for r,y,z in zip(rows,labels,candidates)):
                raise ValueError('DOWNWARD_ONLY_OR_HARD_PRESERVATION_FAILED')
            removed = [dict(id=r['id'], key=r['key'], gold=gold[r['id']],
                            overall=r['score'], final=r['final_score'], ranked_by=r['ranked_by'])
                       for r,y,z in zip(rows,labels,candidates) if z and not y]
            result['arms'][arm] = dict(before=verified['arms'][arm]['quota70'],
                after=dict(metrics=metrics(rows,gold,labels), positives=sum(labels)),
                false_positives_removed=sum(r['gold'] == 0 for r in removed),
                true_positives_lost=sum(r['gold'] == 1 for r in removed),
                preserved_hard_rows=sum(bool(r['hard']) for r in rows), removed_rows=removed,
                retained_false_positives=[dict(id=r['id'], ranked_by=r['ranked_by'])
                    for r,y in zip(rows,labels) if y and gold[r['id']] == 0])
            output += [dict(arm=arm,id=r['id'],gold=gold[r['id']],candidate70=z,label=y,hard=bool(r['hard']),
                            ranked_by=r['ranked_by']) for r,y,z in zip(rows,labels,candidates)]
    (out / 'RESULTS.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    with (out / 'predictions.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=['arm','id','gold','candidate70','label','hard','ranked_by'])
        writer.writeheader(); writer.writerows(output)
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('run-archive','label-archive','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(diagnostic(args.run_archive,args.label_archive,args.out),indent=2))

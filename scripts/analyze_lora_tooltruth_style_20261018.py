"""Join frozen style-control receipts to local gold; no model or training access."""
import argparse
import hashlib
import json
from pathlib import Path

from analyze_lora_tooltruth_20261018 import assess
from audit_lora_results_cpu_20261018 import read


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study', type=Path, required=True)
    a = p.parse_args()
    folder = a.study / 'style'
    done = json.loads((folder / 'DONE.json').read_bytes())
    trained = json.loads((a.study / 'run/TRAINED.json').read_bytes())
    plan = json.loads((a.study / 'STYLE_PROBE_PLAN.json').read_bytes())
    assert done['complete'] and done['rows'] == 144
    assert done['training_steps_added'] == 0 and not done['evaluation_gold_loaded']
    assert done['adapter_sha256'] == trained['adapter_sha256']
    assert done['input_sha256'] == plan['inputs_sha256'] == digest(a.study / 'style_probe_inputs.jsonl')
    gold = read(a.study / 'style_probe_gold.jsonl')
    inputs = read(a.study / 'style_probe_inputs.jsonl')
    assert len(gold) == len(inputs) == 72
    assert [r['id'] for r in gold] == [r['id'] for r in inputs]
    assert all('label' not in r and 'oracle' not in r for r in inputs)
    requests = read(folder / 'requests.jsonl')
    assert [r['id'] for r in requests] == [r['id'] for r in gold]
    for r in requests:
        assert r['input_sha256'] == hashlib.sha256(r['text'].encode('utf8', 'surrogatepass')).hexdigest()
    req = {r['id']: r for r in requests}
    scores = read(folder / 'scores.jsonl')
    by = {(r['arm'], r['id']): r for r in scores}
    assert len(scores) == len(by) == 144
    original = {r['id']: r for r in read(a.study / 'tooltruth_validation_gold.jsonl')}
    original_scores = {(r['arm'], r['id']): r for r in read(a.study / 'run/scores.jsonl')
                       if r['partition'] == 'tooltruth_validation'}
    for g in gold:
        source = original[g['id'].removeprefix('style:')]
        assert g['label'] == source['label']
        assert g['source_row_sha256'] == hashlib.sha256((source['prompt'] + '\0' + source['response']).encode()).hexdigest()
        for arm in ('base', 'adapter'):
            r = by[arm, g['id']]
            assert r['exact'] and r['input_sha256'] == req[g['id']]['input_sha256']
    pools = {'all': gold}
    pools.update({f'family:{f}': [g for g in gold if g['family'] == f]
                  for f in sorted({g['family'] for g in gold})})
    pools.update({f'domain:{d}': [g for g in gold if g['domain'] == d]
                  for d in sorted({g['domain'] for g in gold})})
    out = dict(schema='tooltruth-style-analysis-v1', adapter_sha256=done['adapter_sha256'],
               scope='DEPENDENT_STYLE_CONTROLS_SAME_HELD_OUT_ENTITIES',
               training_steps_added=0, wall_seconds=done['wall_seconds'], pools={})
    for name, rows in pools.items():
        y = [g['label'] for g in rows]
        variants = {}
        for variant in ('original', 'style'):
            variants[variant] = {}
            for arm in ('base', 'adapter'):
                s = [(by[arm, g['id']]['score'] if variant == 'style' else
                      original_scores[arm, g['id'].removeprefix('style:')]['score']) for g in rows]
                variants[variant][arm] = assess(y, s)
        out['pools'][name] = dict(rows=len(rows), positives=sum(y), variants=variants)
    target = a.study / 'STYLE_ANALYSIS.json'
    target.write_bytes((json.dumps(out, indent=2) + '\n').encode())
    for name, pool in out['pools'].items():
        print(name, json.dumps({v: {arm: dict(auc=m['ranking']['roc_auc'], zero=m['zero'])
                                   for arm, m in arms.items()} for v, arms in pool['variants'].items()}))


if __name__ == '__main__':
    main()

"""Mechanical data/provenance audit BEFORE model calls. No model-derived gold."""
import hashlib
import json
from collections import Counter
from pathlib import Path
import build_dataset as author

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(row):
    return hashlib.sha256((row['prompt'] + '\0' + row['response']).encode()).hexdigest()


def audit():
    dev, sealed = author.build()
    report = {'schema': 'modular-data-audit/1', 'human_review_completed': False,
              'groups': {}, 'historical_exact_input_overlap': [],
              'logical_novelty_limit': 'Generator disjointness is necessary, not proof of semantic novelty. Shared primitives explicitly remain.'}
    all_hashes = {digest(r): r['id'] for split in (dev, sealed) for r, _ in split}
    assert len(all_hashes) == 256
    dev_groups = {g['generator'] for _, g in dev}
    sealed_groups = {g['generator'] for _, g in sealed}
    assert not dev_groups & sealed_groups
    for split_name, split in [('dev', dev), ('sealed', sealed)]:
        for r, gold in split:
            assert set(r) == {'id', 'prompt', 'response'}
            assert r['id'] == gold['id']
            for span in [gold['policy_span'], gold['target_span'], *gold['history_evidence_spans']]:
                assert r[span['source']][span['start']:span['end']] == span['quote']
                assert span['quote']
            assert gold['label'] in (0, 1)
            report['groups'].setdefault(gold['logical_group'], {'n': 0, 'errors': 0})['n'] += 1
            report['groups'][gold['logical_group']]['errors'] += gold['label']
        report[split_name] = {'n': len(split), 'unique_inputs': len({digest(r) for r, _ in split}),
            'labels': dict(Counter(g['label'] for _, g in split)),
            'exact_sources_valid': True}
    # Historical INPUT files only: never inspect previously sealed gold.
    checked = []
    for source in sorted(ROOT.glob('experiments/searh_23/**/dataset/**/*input.jsonl')):
        if HERE in source.parents:
            continue
        checked.append(str(source.relative_to(ROOT)).replace('\\', '/'))
        for line in source.read_text(encoding='utf-8').splitlines():
            old = json.loads(line)
            if {'prompt', 'response'} <= old.keys() and digest(old) in all_hashes:
                report['historical_exact_input_overlap'].append({'source': checked[-1], 'new_id': all_hashes[digest(old)]})
    report['historical_input_files_checked'] = checked
    assert not report['historical_exact_input_overlap']
    # Human queue is DEV ONLY; no human validation is manufactured.
    selected = [item for i in range(8) for item in dev if int(item[0]['id'].rsplit('::', 1)[1]) == i][:50]
    queue = [{'id': r['id'], 'prompt': r['prompt'], 'response': r['response'],
        'proposed_label': g['label'], 'author_reason': g['reason'],
        'sources': [g['policy_span'], *g['history_evidence_spans']],
        'questions': ['Does the policy authorize/prohibit this exact target action or assert this exact fact?',
                      'Are the ID, time, exception scope and requested/completed distinction correct?',
                      'Is any alternative interpretation equally justified?'],
        'review_status': 'PENDING', 'human_label': None} for r, g in selected]
    assert len(queue) == 50
    (HERE / 'dataset/HUMAN_REVIEW_QUEUE50.jsonl').write_text(''.join(json.dumps(q, ensure_ascii=False) + '\n' for q in queue), encoding='utf-8')
    (HERE / 'dataset/audit.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('dev', 'sealed', 'historical_exact_input_overlap')}))


if __name__ == '__main__':
    audit()

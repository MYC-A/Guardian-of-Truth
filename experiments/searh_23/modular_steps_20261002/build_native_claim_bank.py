"""DEV oracle atom inventory isolates native verifier from extraction errors."""
import json
from modular_common import HERE, sha, write


def main():
    inputs = {r['id']: r for r in map(json.loads, (HERE / 'dataset/dev_input.jsonl').read_text(encoding='utf-8').splitlines())}
    gold = {r['id']: r for r in map(json.loads, (HERE / 'dataset/dev_gold.jsonl').read_text(encoding='utf-8').splitlines())}
    ids = [f'{g}::{i:02}' for g in ('dev_implication', 'dev_latest', 'dev_entity_binding') for i in (0, 1)]
    bank, labels = [], []
    for cid in ids:
        for i, atom in enumerate(gold[cid]['atomic_claims']):
            bank.append({'id': cid + '/atom' + str(i), 'case_id': cid,
                         'document': inputs[cid]['prompt'], 'claim': atom['text'],
                         'provenance': 'AUTHOR_ORACLE_ATOM_INVENTORY_NOT_END_TO_END_ATOMIZATION'})
            labels.append({'id': bank[-1]['id'], 'relation': atom['relation'], 'group': gold[cid]['logical_group']})
    folder = HERE / 'dataset/native_claims'
    folder.mkdir(parents=True, exist_ok=True)
    for name, rows in [('input', bank), ('author_gold', labels)]:
        blob = ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in rows).encode()
        (folder / (name + '.jsonl')).write_bytes(blob)
    write(folder / 'manifest.json', {'n': len(bank), 'input_sha256': sha((folder / 'input.jsonl').read_bytes()),
        'author_gold_sha256': sha((folder / 'author_gold.jsonl').read_bytes()), 'threshold': .5,
        'role': 'Oracle claims, full source; tests native verifier only. No service promotion.',
        'model_order': ['minicheck', 'factcg'], 'human_reviewed': False})


if __name__ == '__main__':
    main()

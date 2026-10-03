"""Coverage and fixed-code domain-order replay, without labels or inference.

This is an assembly-order invariance check. Cached replies cannot turn already
inspected public policies into prospectively unseen held-out domains.
"""
from collections import defaultdict, Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from guardian_truth.policy_table.compile import assemble
from guardian_truth.policy_table.schema import Table
from guardian_truth.policy_table.segment import policy_hash
from guardian_truth.source_search.store import SourceStore


def run():
    source = ROOT / 'outputs/searh_23/source_search_20261002/comparison_ids_v5/inputs.jsonl'
    groups = defaultdict(list)
    for line in source.read_text(encoding='utf-8').splitlines():
        store = SourceStore(json.loads(line)); groups[policy_hash(store)].append(store)
    freeze_path = ROOT / 'outputs/searh_23/v10/compiler_resume_02/frozen.json'
    freeze = json.loads(freeze_path.read_text(encoding='utf-8'))
    core_seal = {name: value for name, value in freeze['source_sha256'].items() if name.startswith('src/guardian_truth/policy_table/')}
    for name, value in core_seal.items():
        archived = subprocess.check_output(['git', 'show', '111a3a73:' + name], cwd=ROOT)
        if hashlib.sha256(archived).hexdigest() != value: raise ValueError('archived compiler core changed: ' + name)
    tables, compiled = {}, {}
    for key, stores in sorted(groups.items()):
        table = Table.model_validate_json((ROOT / 'outputs/searh_23/policy_tables' / (key + '.json')).read_text(encoding='utf-8'))
        tables[key] = table
        compiled[key] = assemble(stores, table.samples).model_dump(exclude={'compilation_metadata'})
        if compiled[key] != table.model_dump(exclude={'compilation_metadata'}): raise ValueError('saved table is not reproducible: ' + key)
    directory = ROOT / 'outputs/searh_23/v10/policy_table_audit'
    directory.mkdir(parents=True, exist_ok=True)
    coverage = []
    for key, table in tables.items():
        coverage.append({'policy_sha256': key, 'cases': len(groups[key]), 'surface_clauses': len(table.clauses),
            'agreement_rules': dict(Counter(r['status'] for r in table.rules)),
            'coverage': {name: len(value) for name, value in table.coverage.items() if isinstance(value, list)},
            'discarded_reasons': dict(Counter(r['reason'] for r in table.discarded)),
            'wire_rejections': sum(r['operation'] == 'REJECT_SCHEMA_INVALID_CANDIDATE' for r in table.compilation_metadata.get('wire_admission_receipts', [])),
            'uncovered': [{'clause_id': c['id'], 'text': c['text']} for c in table.clauses if c['id'] in table.coverage['uncovered']]})
    (directory / 'coverage.json').write_text(json.dumps({'status': 'COMPILED_ZERO_ADMITTED_RULES' if not any(t.rules for t in tables.values()) else 'COMPILED',
        'source_inputs_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'compiler_core_sha256': core_seal,
        'policies': coverage, 'api_calls_for_audit': 0, 'labels_opened': False,
        'limitation': 'Confirmation/current datetime were unwitnessed; zero admission is not a complete semantic-parser test.'}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for heldout in sorted(groups):
        order = [key for key in sorted(groups) if key != heldout] + [heldout]
        for key in order:
            replay = assemble(groups[key], tables[key].samples).model_dump(exclude={'compilation_metadata'})
            if replay != compiled[key]: raise ValueError('assembly-order difference')
        receipt = {'status': 'FROZEN_DOMAIN_ORDER_REPLAY', 'held_out_policy_sha256': heldout,
            'assembly_order': order, 'held_out_assembled_last': True, 'compiler_core_sha256': core_seal,
            'schema_tuned_between_domains': False, 'parameters_fitted_to_domains': False,
            'model_replies': 'REUSED_ORIGINAL_THREE_SAMPLES_PER_HASH; NO_REASK',
            'prospectively_unseen_domain_claim': False, 'original_request_order': 'LEXICAL_POLICY_HASH_ORDER',
            'limitation': 'This verifies fixed-code order invariance, not four separate prospectively blind model runs.',
            'table_false_positives': 'NOT_SCORED_BEFORE_FINAL_PREDICTION_FREEZE', 'labels_opened': False, 'api_calls': 0}
        (directory / ('lodo_' + heldout + '.json')).write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'policies': len(tables), 'admitted_rules': sum(len(t.rules) for t in tables.values()), 'lodo_order_replays': len(groups), 'api_calls': 0}))


if __name__ == '__main__': run()

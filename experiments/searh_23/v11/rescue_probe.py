"""Small, frozen, label-free A one-shot vs B obligation ledger experiment."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from prepare import OUTPUT, write, groups
from guardian_truth.policy_table_v11.compile import request, admit, canonical
from guardian_truth.policy_table_v11.obligations import extraction_request, admit_ledger, lowering_request, admit_lowerings
from guardian_truth.policy_table_v11.schema import Atom
from guardian_truth.policy_table_v11.transport import Transport
from guardian_truth.source_search.pipeline import decode_model_object
import run as original

RUN = ROOT / 'outputs/searh_23/v11/rescue_probe'
MODELS = [
    {'model': 'gpt-oss:120b', 'provider': 'ollama', 'family': 'gpt-oss', 'reasoning_effort': 'high', 'max_output_tokens': 32768},
    {'model': 'nemotron-3-ultra', 'provider': 'ollama', 'family': 'nemotron', 'reasoning_effort': None, 'max_output_tokens': 12288},
    {'model': 'gemma4:31b', 'provider': 'ollama', 'family': 'gemma', 'reasoning_effort': None, 'max_output_tokens': 8192},
]


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def freeze():
    if (RUN / 'freeze.json').exists(): raise ValueError('freeze_already_exists')
    cases = []
    for path in sorted(OUTPUT.glob('*.json')):
        if len(path.stem) != 64: continue
        policy = json.loads(path.read_text(encoding='utf-8'))
        tool = min(n for n, spec in policy['catalog']['tools'].items() if spec['role'] != 'READ')
        cases.append({'policy': policy, 'trigger': {'kind': 'TOOL_CALL', 'tool': tool}})
    paths = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / 'src/guardian_truth').rglob('*.py'))
    paths += ['experiments/searh_23/v11/rescue_probe.py', 'experiments/searh_23/v11/run.py',
              'experiments/searh_23/v11/prepare.py', 'experiments/searh_23/v11/measure.py',
              'docs/v11/UNIVERSAL_RESCUE_PROTOCOL_2026-10-03.md']
    paths += ['outputs/searh_23/v11/rescue_probe/source_expectations.json',
              'outputs/searh_23/source_search_20261002/comparison_ids_v5/inputs.jsonl',
              'outputs/searh_23/v10/mutations_preparation/inputs.jsonl',
              'outputs/searh_23/v10/mutations_preparation/expectations.jsonl']
    paths += sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / 'tests').glob('test_policy_table_v11*.py'))
    value = {'version': 'v11-rescue-probe/1', 'cases': cases, 'models': MODELS,
        'sources': {p: subprocess.check_output(['git', 'hash-object', p], cwd=ROOT, text=True).strip() for p in paths},
        'ledger': original.LEDGER, 'limits': {'http': 450, 'tokens': 3000000},
        'syntax_retries': 1, 'timeout': 300, 'temperature': 0, 'gold_opened': False,
        'ledger_chunk_size': 64,
        'combination': 'NO_PRODUCTION_CHANGE', 'selection': 'LEXICOGRAPHIC_FIRST_NON_READ_TOOL_PER_POLICY',
        'baseline_archive': 'outputs/searh_23/v11/pilot_52861003_audit.zip'}
    write(RUN / 'freeze.json', value)
    return {'cases': [(c['policy']['policy_sha256'][:8], c['trigger']['tool']) for c in cases], 'models': [m['model'] for m in MODELS]}


def verify():
    path = RUN / 'freeze.json'
    expected = json.loads(subprocess.check_output(['git', 'show', 'HEAD:' + path.relative_to(ROOT).as_posix()], cwd=ROOT))
    if expected != json.loads(path.read_text(encoding='utf-8')): raise ValueError('freeze_not_committed')
    for p, blob in expected['sources'].items():
        if subprocess.check_output(['git', 'hash-object', p], cwd=ROOT, text=True).strip() != blob:
            raise ValueError('frozen_source_changed:' + p)
    return expected


def call(messages, model, stage, frozen):
    config = {**model, 'timeout': frozen['timeout'], 'temperature': frozen['temperature']}
    uid = fingerprint({'version': frozen['version'], 'messages': messages, 'config': config, 'stage': stage})
    path = RUN / 'replies' / (uid + '.json')
    if path.exists() and (saved := json.loads(path.read_text(encoding='utf-8'))).get('complete'): return saved
    t = Transport(frozen['ledger'], model['provider'], model['model'], reasoning_effort=model['reasoning_effort'],
                  max_output_tokens=model['max_output_tokens'], timeout=frozen['timeout'], temperature=frozen['temperature'])
    record = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'request_sha256': uid, 'stage': stage,
        'model': model, 'reply': t(messages, fresh_sample=uid), 'retry': None}
    write(path, record)  # raw first, before decoding/admission
    record['decoded'] = None; record['outcome'] = record['reply']['status']
    if record['reply']['status'] == 'OK':
        finish = record['reply'].get('provider_response', {}).get('choices', [{}])[0].get('finish_reason')
        if finish == 'length': record['outcome'] = 'LENGTH'
        else:
            try: record['decoded'] = decode_model_object(record['reply'].get('content'))
            except (ValueError, TypeError):
                record['retry'] = record.get('retry') or t(messages, fresh_sample=uid + '/syntax_retry')
                write(path, record)
                if record['retry']['status'] == 'OK':
                    retry_finish = record['retry'].get('provider_response', {}).get('choices', [{}])[0].get('finish_reason')
                    if retry_finish == 'length': record['outcome'] = 'LENGTH'
                    else:
                        try: record['decoded'] = decode_model_object(record['retry'].get('content'))
                        except (ValueError, TypeError): pass
                else: record['outcome'] = record['retry']['status']
        if record['decoded'] is None and record['outcome'] == 'OK': record['outcome'] = 'INVALID_JSON'
    record['complete'] = True
    write(path, record)
    return record


def run_probe():
    frozen = verify(); rows = []
    for case in frozen['cases']:
        policy, trigger = case['policy'], case['trigger']
        for model in frozen['models']:
            t = Transport(frozen['ledger'], model['provider'], model['model'])
            state = t.snapshot()
            if state['auth_stop'] or state['http_attempts'] >= 450 or state['known_tokens'] + state['unknown_upper_bound'] >= 3000000: break
            a = call(request(policy, trigger), model, 'A_ONE_SHOT', frozen)
            admitted_a = admit(a['decoded'], policy, trigger)
            chunks, merged = [], []
            for start in range(0, len(policy['clauses']), frozen['ledger_chunk_size']):
                ids = [c['id'] for c in policy['clauses'][start:start + frozen['ledger_chunk_size']]]
                b = call(extraction_request(policy, trigger, ids), model, 'B_LEDGER/' + str(start), frozen)
                checked = admit_ledger(b['decoded'], policy, ids)
                chunks.append({'receipt': b['request_sha256'], 'outcome': b['outcome'], 'admission': checked})
                if checked['valid']:
                    for clause in checked['ledger']['clauses']:
                        data = json.loads(json.dumps(clause))
                        for obligation in data['obligations']: obligation['id'] = str(start) + '/' + obligation['id']
                        merged.append(data)
            ledger = admit_ledger({'clauses': merged}, policy)
            lowered = {'valid': False, 'atoms': [], 'reason': 'ledger_invalid'}; lower = None
            if ledger['valid']:
                lower = call(lowering_request(policy, trigger, ledger), model, 'B_LOWER', frozen)
                lowered = admit_lowerings(lower['decoded'], ledger, policy, trigger)
            row = {'policy': policy['policy_sha256'], 'trigger': trigger, 'model': model,
                'A': {'receipt': a['request_sha256'], 'outcome': a['outcome'], 'admission': admitted_a},
                'B': {'chunks': chunks, 'outcome': 'OK' if all(c['outcome'] == 'OK' for c in chunks) else 'CHUNK_FAILURE', 'ledger': ledger,
                      'lower_receipt': lower['request_sha256'] if lower else None,
                      'lower_outcome': lower['outcome'] if lower else 'NOT_RUN', 'admission': lowered}}
            rows.append(row); write(RUN / 'progress.json', {'rows': rows, 'budget': t.snapshot(), 'gold_opened': False})
            print(json.dumps({'policy': policy['policy_sha256'][:8], 'tool': trigger['tool'], 'model': model['model'],
                'A_atoms': len(admitted_a['atoms']), 'ledger_valid': ledger['valid'], 'B_atoms': len(lowered['atoms']),
                'budget': t.snapshot()}), flush=True)
    write(RUN / 'result.json', {'rows': rows, 'budget': Transport(frozen['ledger'], 'mistral').snapshot(), 'gold_opened': False})
    return report()


def report():
    frozen = verify(); raw = json.loads((RUN / 'result.json').read_text(encoding='utf-8')); rows = raw['rows']
    metrics, pairwise = [], []
    def cost(row, arm):
        receipts = [row[arm].get('receipt')] if arm == 'A' else [c['receipt'] for c in row['B']['chunks']]
        if arm == 'B': receipts.append(row[arm].get('lower_receipt'))
        known, unknown, seconds, attempts = 0, 0, 0, 0
        for uid in receipts:
            if uid is None: continue
            record = json.loads((RUN / 'replies' / (uid + '.json')).read_text(encoding='utf-8'))
            for response in [record['reply'], record.get('retry')]:
                if response and 'attempt_id' in response:
                    known += response.get('known_tokens', 0)
                    unknown += response.get('unknown_upper_bound', 0)
                    seconds += response.get('seconds', 0)
                    attempts += 1
        return {'known_tokens': known, 'unknown_upper_bound': unknown, 'seconds': seconds, 'http_attempts': attempts}
    def candidates(row):
        total = 0
        for chunk in row['B']['chunks']:
            record = json.loads((RUN / 'replies' / (chunk['receipt'] + '.json')).read_text(encoding='utf-8'))
            decoded = record.get('decoded')
            if not isinstance(decoded, dict) or not isinstance(decoded.get('clauses'), list): continue
            total += sum(len(c['obligations']) for c in decoded['clauses']
                         if isinstance(c, dict) and isinstance(c.get('obligations'), list))
        return total
    for model in frozen['models']:
        own = [r for r in rows if r['model'] == model]
        metrics.append({'model': model['model'], 'cases': len(own),
            'expected_cases': len(frozen['cases']), 'missing_cases': len(frozen['cases']) - len(own),
            'A_valid': sum(r['A']['admission']['valid_response'] for r in own),
            'A_atoms': sum(len(r['A']['admission']['atoms']) for r in own),
            'B_ledger_valid': sum(r['B']['ledger']['valid'] for r in own),
            'B_lower_valid': sum(r['B']['admission']['valid'] for r in own),
            'B_obligations': sum(len(r['B']['ledger']['obligations']) for r in own),
            'B_raw_candidates': sum(candidates(r) for r in own),
            'B_unaccounted_candidates': sum(candidates(r) for r in own if not r['B']['ledger']['valid']),
            'B_atoms': sum(len(r['B']['admission']['atoms']) for r in own),
            'B_unsupported': sum(r['B']['admission'].get('unsupported', 0) for r in own),
            'B_ambiguous': sum(r['B']['admission'].get('ambiguous', 0) for r in own),
            'B_rejected': sum(r['B']['admission'].get('rejected', 0) for r in own),
            'A_cost': {field: sum(cost(r, 'A')[field] for r in own) for field in ['known_tokens', 'unknown_upper_bound', 'seconds', 'http_attempts']},
            'B_cost': {field: sum(cost(r, 'B')[field] for r in own) for field in ['known_tokens', 'unknown_upper_bound', 'seconds', 'http_attempts']},
            'outcomes_A': dict(Counter(r['A']['outcome'] for r in own)),
            'outcomes_B_ledger': dict(Counter(r['B']['outcome'] for r in own)),
            'outcomes_B_lower': dict(Counter(r['B']['lower_outcome'] for r in own))})
    for case in frozen['cases']:
        key, trigger = case['policy']['policy_sha256'], case['trigger']
        own = [r for r in rows if r['policy'] == key]
        for arm in ['A', 'B']:
            sets = {r['model']['family']: {canonical(key, trigger, Atom.model_validate(a))
                    for a in r[arm]['admission']['atoms']} for r in own}
            votes = Counter(k for values in sets.values() for k in values)
            pairwise.append({'policy': key, 'trigger': trigger, 'arm': arm,
                'shared_2': sum(n >= 2 for n in votes.values()), 'shared_3': sum(n == 3 for n in votes.values()),
                'vote_counts': dict(votes)})
    control_rows = []
    for model in frozen['models']:
        for arm in ['A', 'B']:
            proposals = [{'trigger': r['trigger'], 'admission': r[arm]['admission']} for r in rows
                         if r['model'] == model and r['policy'] == original.PILOT]
            if proposals:
                p = next(c['policy'] for c in frozen['cases'] if c['policy']['policy_sha256'] == original.PILOT)
                control_rows.append({'model': model['model'], 'arm': arm, **original.controls(proposals, p)})
    value = {'metrics': metrics, 'agreement': pairwise, 'negative_controls': control_rows,
             'budget': raw['budget'], 'gold_opened': False, 'semantic_completeness_proven': False,
             'detector_improvement_measured': False}
    write(RUN / 'score_label_free.json', value)
    return value


if __name__ == '__main__':
    phase = sys.argv[1]
    result = freeze() if phase == 'freeze' else run_probe() if phase == 'run' else report() if phase == 'report' else None
    if result is None: raise ValueError('unknown_phase')
    print(json.dumps(result, ensure_ascii=False))

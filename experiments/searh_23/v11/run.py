"""Frozen label-free pilot and full compilation. Raw replies precede atom admission."""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from prepare import groups, write, OUTPUT
from guardian_truth.policy_table_v11.compile import request, admit, canonical, assemble
from guardian_truth.policy_table_v11.schema import Atom
from guardian_truth.policy_table_v11.evaluate import evaluate_atom
from guardian_truth.policy_table_v11.transport import Transport
from guardian_truth.source_search.pipeline import decode_model_object
from guardian_truth.source_search.id_contract import native_target_inventory
from guardian_truth.source_search.store import SourceStore

RUN = ROOT / 'outputs/searh_23/v11'
PILOT = 'da31c80eff47a6cda99c1029c08d18f1a719616fdfcfd836b60ca33ee4ce806a'
LEDGER = '/workspace/guardian/results/v11-policy-table-20261003'
CANDIDATES = [('gpt-oss:120b', 'ollama', 'gpt-oss', 'high'),
    ('nemotron-3-ultra', 'ollama', 'nemotron', None),
    ('MISTRAL_STRONGEST_AVAILABLE', 'mistral', 'mistral', None),
    ('gemma4:31b', 'ollama', 'gemma', None)]


def source_files():
    files = list((ROOT / 'src/guardian_truth/policy_table_v11').glob('*.py')) + list((ROOT / 'experiments/searh_23/v11').glob('*.py'))
    files += [ROOT / 'docs/v11/PLAN.md', ROOT / 'outputs/searh_23/source_search_20261002/comparison_ids_v5/inputs.jsonl']
    return sorted(p.relative_to(ROOT).as_posix() for p in files)


def freeze(stage, models=None):
    value = {'stage': stage, 'code_git_blobs': {p: subprocess.check_output(['git', 'hash-object', p], cwd=ROOT, text=True).strip() for p in source_files()},
        'models': models, 'budget': {'http': 450, 'tokens': 3000000}, 'ledger': LEDGER,
        'combination': 'OLD_DIRECT_ERROR_OR_DECISIVE_FINDING', 'gold_opened': False,
        'policy_inventory': {p.stem: hashlib.sha256(p.read_bytes()).hexdigest() for p in OUTPUT.glob('*.json') if len(p.stem) == 64}}
    write(RUN / (stage + '_freeze.json'), value)
    return value


def verify(stage):
    path = RUN / (stage + '_freeze.json')
    sealed = json.loads(subprocess.check_output(['git', 'show', 'HEAD:' + path.relative_to(ROOT).as_posix()], cwd=ROOT))
    actual = json.loads(path.read_text(encoding='utf-8'))
    if actual != sealed: raise ValueError('freeze_not_committed')
    for relative, blob in sealed['code_git_blobs'].items():
        if subprocess.check_output(['git', 'hash-object', relative], cwd=ROOT, text=True).strip() != blob:
            raise ValueError('source_changed_since_freeze:' + relative)
    for key, digest in sealed['policy_inventory'].items():
        # JSON artifacts are newline-normalized via parsed canonical representation below.
        raw = (OUTPUT / (key + '.json')).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest and hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest() != digest:
            # Windows artifacts frozen with CRLF need inverse normalization on Linux.
            if hashlib.sha256(raw.replace(b'\n', b'\r\n')).hexdigest() != digest: raise ValueError('policy_inventory_changed:' + key)
    return sealed


def transport(model):
    return Transport(LEDGER, model['provider'], model['model'], reasoning_effort=model.get('reasoning_effort'))


def availability():
    verify('pilot')
    path = RUN / 'pilot/availability.json'
    if path.exists(): return json.loads(path.read_text(encoding='utf-8'))
    models = []; records = []
    for name, provider, family, effort in CANDIDATES:
        if provider == 'mistral':
            t = Transport(LEDGER, provider)
            listing = t.list_models(); write(RUN / 'pilot/mistral_models.json', listing)
            records.append({'operation': 'models', 'reply': listing})
            if listing['status'] in ('AUTH_STOP', 'BUDGET_STOP') or t.snapshot()['auth_stop']: break
            if listing['status'] != 'OK': continue
            choices = ['mistral-large-latest', 'magistral-medium-latest', 'mistral-medium-latest', 'ministral-14b-latest']
            name = next((n for n in choices if n in listing['models']), None)
            if name is None: continue
        config = {'model': name, 'provider': provider, 'family': family, 'reasoning_effort': effort}
        t = Transport(LEDGER, provider, name, reasoning_effort=effort, max_output_tokens=128)
        reply = t([{'role': 'user', 'content': 'Reply with OK.'}]); records.append({'config': config, 'reply': reply})
        if reply['status'] == 'OK': models.append(config)
        elif name == 'nemotron-3-ultra' and reply.get('http_status') not in (401, 402, 403, 429) and not t.snapshot()['auth_stop']:
            config = {**config, 'model': 'nemotron-3-super'}
            reply = Transport(LEDGER, provider, config['model'], max_output_tokens=128)([{'role': 'user', 'content': 'Reply with OK.'}])
            records.append({'config': config, 'reply': reply})
            if reply['status'] == 'OK': models.append(config)
        if reply['status'] in ('AUTH_STOP', 'BUDGET_STOP') or t.snapshot()['auth_stop']: break
    result = {'models': models, 'records': records, 'budget': Transport(LEDGER, 'mistral').snapshot()}
    write(path, result); return result


def proposal(policy, trigger, model, sample_id=0):
    uid = hashlib.sha256(json.dumps([policy['policy_sha256'], trigger, model, sample_id], sort_keys=True).encode()).hexdigest()[:24]
    path = RUN / 'replies' / (uid + '.json')
    if path.exists() and 'admission' in json.loads(path.read_text(encoding='utf-8')):
        return json.loads(path.read_text(encoding='utf-8'))
    messages = request(deepcopy(policy), trigger, sample_id)
    t = transport(model)
    existing = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    reply = existing['reply'] if existing else t(messages, fresh_sample=uid)
    record = existing or {'policy': policy['policy_sha256'], 'trigger': trigger, 'config': model,
        'proposer': model['family'] + '/' + model['model'] + '/' + str(sample_id), 'family': model['family'],
        'request_sha256': hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        'reply': reply, 'response': None, 'retry': None}
    write(path, record)  # Before JSON decoding/admission.
    if reply['status'] == 'OK':
        try: record['response'] = decode_model_object(reply.get('content'))
        except (ValueError, TypeError):
            # Same exact prompt; only syntax failure warrants the single allowed technical retry.
            retry = t(messages, fresh_sample=uid + '/json_retry'); record['retry'] = retry; write(path, record)
            if retry['status'] == 'OK':
                try: record['response'] = decode_model_object(retry.get('content'))
                except (ValueError, TypeError): pass
    parsed = admit(record['response'], policy, trigger)
    record['admission'] = parsed; write(path, record)
    return record


def check_stopped():
    t = Transport(LEDGER, 'mistral'); s = t.snapshot()
    return s['auth_stop'] or s['http_attempts'] >= 450 or s['known_tokens'] + s['unknown_upper_bound'] >= 3000000


def atom_findings(store, proposals, policy):
    found = set()
    for p in proposals:
        for raw in p.get('admission', {}).get('atoms', []):
            atom = Atom.model_validate(raw)
            for target in native_target_inventory(store):
                if p['trigger'].get('tool') != target['tool']: continue
                if evaluate_atom(store, atom, target)['finding']:
                    found.add((canonical(policy['policy_sha256'], p['trigger'], atom), target['source_id']))
    return found


def controls(proposals, policy):
    originals = {s.case_id: s for stores in groups().values() for s in stores}
    folder = ROOT / 'outputs/searh_23/v10/mutations_preparation'
    inputs = {r['id']: r for r in map(json.loads, (folder / 'inputs.jsonl').read_text(encoding='utf-8').splitlines())}
    rows = []
    for expectation in map(json.loads, (folder / 'expectations.jsonl').read_text(encoding='utf-8').splitlines()):
        if expectation['policy_sha256'] != policy['policy_sha256']: continue
        base = atom_findings(originals[expectation['base_case_id']], proposals, policy)
        changed = atom_findings(SourceStore(inputs[expectation['id']]), proposals, policy)
        rows.append({'id': expectation['id'], 'added': len(changed - base), 'removed': len(base - changed)})
    return {'controls': len(rows), 'added_findings': sum(r['added'] for r in rows), 'cases': rows}


def pilot():
    verify('pilot'); available = availability(); models = available['models']
    policy = json.loads((OUTPUT / (PILOT + '.json')).read_text(encoding='utf-8'))
    metrics, all_proposals = [], {}
    for rank, model in enumerate(models):
        replies = []
        for tool in sorted(policy['catalog']['tools']):
            if check_stopped(): break
            record = proposal(policy, {'kind': 'TOOL_CALL', 'tool': tool}, model)
            replies.append(record)
            if record['reply']['status'] == 'BUDGET_STOP': break
        valid = sum(r.get('admission', {}).get('valid_response', False) for r in replies)
        atoms = [canonical(PILOT, r['trigger'], Atom.model_validate(a)) for r in replies for a in r.get('admission', {}).get('atoms', [])]
        control = controls(replies, policy)
        entry = {'config': model, 'rank': rank, 'responses': len(replies), 'valid_fraction': valid / len(policy['catalog']['tools']),
            'admitted_atom_count': len(atoms), 'unique_atoms': len(set(atoms)),
            'empty_unmotivated': sum(r.get('admission', {}).get('empty_unmotivated', False) for r in replies),
            'negative_controls': control}
        metrics.append(entry); all_proposals[model['model']] = set(atoms)
        write(RUN / 'pilot/progress.json', {'metrics': metrics, 'budget': transport(model).snapshot()})
        print(json.dumps({'model': model['model'], 'valid': valid, 'atoms': len(atoms), 'controls_added': control['added_findings'], 'budget': transport(model).snapshot()}), flush=True)
    pairwise = [{'a': a, 'b': b, 'shared': len(all_proposals[a] & all_proposals[b]),
        'union': len(all_proposals[a] | all_proposals[b])} for i, a in enumerate(all_proposals) for b in list(all_proposals)[i+1:]]
    eligible = sorted([m for m in metrics if m['valid_fraction'] >= .9 and m['negative_controls']['added_findings'] == 0],
        key=lambda m: (-m['admitted_atom_count'], -m['valid_fraction'], m['rank']))
    selected = [dict(m['config'], sample_id=0) for m in eligible[:3]]
    fallback = len({m['family'] for m in selected}) < 2
    if selected:
        while len(selected) < 3:
            selected.append(dict(selected[0], sample_id=len(selected)))
    result = {'status': 'SELECTED' if len(selected) == 3 else 'NO_ELIGIBLE_MODEL', 'metrics': metrics,
        'pairwise': pairwise, 'selected': selected, 'family_fallback': fallback,
        'gold_opened': False, 'budget': Transport(LEDGER, 'mistral').snapshot()}
    write(RUN / 'pilot/result.json', result)
    return result


def compile_all():
    frozen = verify('final'); selection = frozen['models']; models = selection['selected']
    for path in sorted(OUTPUT.glob('*.json')):
        if len(path.stem) != 64: continue
        policy = json.loads(path.read_text(encoding='utf-8')); records = []
        triggers = [{'kind': 'TOOL_CALL', 'tool': name} for name in sorted(policy['catalog']['tools'])] + [
            {'kind': 'SPEECH_ACT', 'act': name} for name in ['TRANSFER', 'REFUSE']]
        for trigger in triggers:
            for model in models:
                if check_stopped(): break
                record = proposal(policy, trigger, {k: v for k, v in model.items() if k != 'sample_id'}, model['sample_id'])
                records.append({k: record[k] for k in ('proposer', 'family', 'trigger', 'response')})
                if record['reply']['status'] == 'BUDGET_STOP': break
        # Missing requests still count as absent proposals, never promote two votes to three.
        for model in models:
            proposer_id = model['family'] + '/' + model['model'] + '/' + str(model['sample_id'])
            if not any(r['proposer'] == proposer_id for r in records):
                records.append({'proposer': proposer_id, 'family': model['family'], 'trigger': triggers[0], 'response': None})
        table = assemble(policy, records, family_fallback=selection['family_fallback'])
        write(RUN / 'tables' / (policy['policy_sha256'] + '.json'), table)
        print(json.dumps({'policy': policy['policy_sha256'][:8], 'atoms': len(table['atoms']), 'discarded': len(table['discarded']),
            'budget': Transport(LEDGER, 'mistral').snapshot()}), flush=True)


if __name__ == '__main__':
    phase = sys.argv[1]
    if phase == 'freeze-pilot': result = freeze('pilot')
    elif phase == 'freeze-final': result = freeze('final', json.loads((RUN / 'pilot/result.json').read_text(encoding='utf-8')))
    elif phase == 'pilot': result = pilot()
    elif phase == 'compile': compile_all(); result = Transport(LEDGER, 'mistral').snapshot()
    else: raise ValueError('unknown_phase')
    if result is not None: print(json.dumps(result, ensure_ascii=False))

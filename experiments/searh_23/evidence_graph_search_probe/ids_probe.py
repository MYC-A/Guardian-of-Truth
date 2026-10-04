"""A new frozen phase after the address-only experiment, without gold labels.

The predecessor is not repaired or overwritten. This candidate gives code full
ownership of source addresses and enforces formula arity in the wire schema.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'evidence_graph_v1'))
from span_ids import IdGraph
from guardian_truth.parsing import decode_json
from guardian_truth.source_search.store import SourceStore, digest
from offline import rows, write, sha, canonical_source_sha, code_fingerprint
from probe import body


def fingerprints():
    files = list(Path(__file__).parent.glob('*.py'))
    files += list((Path(__file__).parent.parent / 'evidence_graph_v1').glob('*.py'))
    return {**code_fingerprint(), **{p.relative_to(ROOT).as_posix(): canonical_source_sha(p) for p in files}}


def graphs(out):
    return [(row['id'], IdGraph(SourceStore(row))) for row in rows(out / 'inputs.jsonl')]


def export(out, protocol, pairs, name, stage):
    requests = {}
    for cid, graph in pairs:
        jobs = graph.initial_jobs() if stage == 'initial' else graph.pending_jobs()
        for job in jobs:
            wire = body(job, protocol['model_id'])
            key = digest(wire)
            if (out / 'raw' / (key + '.json')).exists():
                continue
            entry = requests.setdefault(key, {'request_sha256': key, 'task': job['task'],
                'wire_body': wire, 'uses': []})
            entry['uses'].append({'case_id': cid, 'job_id': job['id']})
    entries = sorted(requests.values(), key=lambda r: (r['task'] != 'EFFECT', r['request_sha256']))
    if stage == 'initial':
        # Exercise the recursive schema in the first counted request. No separate
        # unledgered smoke call, and no silently paid effect batch before a 400.
        first = next((r for r in entries if r['task'] == 'INVENTORY'), None)
        if first is not None:
            entries.remove(first)
            entries.insert(0, first)
    path = out / name
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in entries), encoding='utf-8', newline='\n')
    summary = {'requests': len(entries), 'by_task': dict(Counter(r['task'] for r in entries)),
               'queue_sha256': sha(path), 'protocol_sha256': protocol['protocol_sha256']}
    write(path.with_suffix('.seal.json'), summary)
    return summary


def prepare(args):
    if (args.out / 'protocol.json').exists():
        raise ValueError('OUTPUT_ALREADY_FROZEN')
    args.out.mkdir(parents=True, exist_ok=True)
    source_rows = rows(args.inputs)
    (args.out / 'inputs.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in source_rows),
                                         encoding='utf-8', newline='\n')
    protocol = {'version': 'evidence-graph-code-span-and-arity-probe/1',
        'source_code': fingerprints(), 'input_sha256': sha(args.out / 'inputs.jsonl'),
        'model_id': 'ministral-14b-latest', 'limits': {'http': 160, 'tokens': 800000}, 'timeout': 180,
        'authorization': 'User authorized new API experiments on 2026-10-04',
        'predecessor': 'af999fe275ab3d05305ded88f3c7239fc34633e58209e3dc554abc23390f9db5',
        'parent_expense_policy': 'Predecessor ledger retained and expenses added in final report',
        'changes': ['Code-issued IDs over complete original lines, not semantic segmentation',
                    'Formula arity represented as typed alternatives in JSON schema',
                    'Inventory source anchor restricted to requested unit',
                    'Generic IR interpretation of condition, guard and necessary permission stated explicitly',
                    'Search route hidden from applicability prompt'],
        'data_status': 'KNOWN_PUBLIC_INPUTS_NO_GOLD_READ; development successor after parser errors',
        'decision_scope': 'CURRENT_NATIVE_CALLS_ONLY; SHADOW',
        'stop': 'First HTTP/transport error, including saved error recovered on startup',
        'semantic_completeness_proven': False,
        'retrieval_preparation': 'BM25 over entire source windows; BFS/DFS available, not yet measured'}
    selection = args.out / 'target_selection.json'
    if selection.exists():
        protocol['target_selection_sha256'] = sha(selection)
    protocol['protocol_sha256'] = digest(protocol)
    write(args.out / 'protocol.json', protocol)
    return export(args.out, protocol, graphs(args.out), 'initial.jsonl', 'initial')


def replay(args):
    protocol = json.loads((args.out / 'protocol.json').read_text(encoding='utf-8'))
    if digest({k: v for k, v in protocol.items() if k != 'protocol_sha256'}) != protocol['protocol_sha256']:
        raise ValueError('PROTOCOL_CHANGED')
    if protocol['source_code'] != fingerprints() or protocol['input_sha256'] != sha(args.out / 'inputs.jsonl'):
        raise ValueError('FROZEN_CODE_OR_INPUT_CHANGED')
    raw = {}
    for path in (args.out / 'raw').glob('*.json'):
        record = json.loads(path.read_text(encoding='utf-8'))
        key = record['request_sha256']
        if key in raw or path.name != key + '.json':
            raise ValueError('DUPLICATE_OR_MISNAMED_CACHE')
        if record['protocol_sha256'] != protocol['protocol_sha256'] or record['model_id'] != protocol['model_id']:
            raise ValueError('CACHE_PROTOCOL_OR_MODEL_MISMATCH')
        raw[key] = record
    pairs = graphs(args.out)
    admissions = []
    for cid, graph in pairs:
        for _ in range(8):
            progress = False
            for job in graph.pending_jobs():
                key = digest(body(job, protocol['model_id']))
                record = raw.get(key)
                if not record:
                    continue
                choice = (record.get('provider_response', {}).get('choices') or [{}])[0]
                content = choice.get('message', {}).get('content')
                reply, valid = decode_json(content) if isinstance(content, str) else (None, False)
                if record['status'] != 'OK' or not valid or not isinstance(reply, dict) or choice.get('finish_reason') != 'stop':
                    result = {'valid': False, 'cause': 'PROVIDER_INVALID_OR_UNFINISHED_JSON'}
                    graph.failures[job['id']] = {'task': job['task'], 'key': job['key'], **result}
                else:
                    result = graph.admit(job['id'], reply)
                admissions.append({'case_id': cid, 'request_sha256': key, 'task': job['task'], **result})
                progress = True
            if not progress:
                break
    unique = {r['request_sha256']: r for r in admissions}
    reports = [{'id': cid, **graph.report()} for cid, graph in pairs]
    write(args.out / 'reports.json', reports)
    write(args.out / 'admissions.json', admissions)
    write(args.out / 'extracted.json', [{'id': cid, 'inventories': graph.inventories,
        'effects': graph.effects, 'requirements': graph.requirements,
        'links': list(graph.links.values()),
        'witnesses': [w for replies in graph.witnesses.values() for w in replies]}
        for cid, graph in pairs])
    score = {'unique_responses': len(unique),
        'admitted_by_task': dict(Counter(r['task'] for r in unique.values() if r['valid'])),
        'failed_by_task': dict(Counter(r['task'] for r in unique.values() if not r['valid'])),
        'failure_causes': dict(Counter(r['cause'] for r in unique.values() if not r['valid'])),
        'requirements_logical': sum(len(g.requirements) for _, g in pairs),
        'candidate_decisions': dict(Counter(t['candidate_decision'] for r in reports for t in r['targets'])),
        'semantic_completeness_proven': False}
    write(args.out / 'score.json', score)
    if args.export_next:
        score['next'] = export(args.out, protocol, pairs, args.export_next, 'pending')
    return score


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['prepare', 'replay'])
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--inputs', type=Path, default=ROOT / 'outputs/searh_23/evidence_graph_v1_sealed/inputs.jsonl')
    p.add_argument('--export-next')
    args = p.parse_args()
    print(json.dumps(prepare(args) if args.phase == 'prepare' else replay(args), ensure_ascii=False))

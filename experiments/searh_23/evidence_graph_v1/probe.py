"""Frozen paired source-address experiment and later graph-search ablations.

A is the unchanged integer-offset parser. B copies exact quotes and code locates
them uniquely in the shown original source. Same model, input and semantic task.
No contest labels are read. No automatic schema repair or re-asking failures.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import pydantic

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).parent))
from guardian_truth.evidence_graph import EvidenceGraph
from guardian_truth.parsing import decode_json
from guardian_truth.source_search.store import SourceStore, digest
from quote_adapter import QuoteGraph
from offline import rows, write, sha, code_fingerprint, canonical_source_sha


def fingerprints():
    return {**code_fingerprint(), **{
        path.relative_to(ROOT).as_posix(): canonical_source_sha(path)
        for path in Path(__file__).parent.glob('*.py')}}


def body(job, model):
    return {'model': model, 'messages': job['messages'], 'temperature': 0,
            'response_format': job['response_format'],
            'max_tokens': 8192 if job['task'] == 'INVENTORY' else 2400}


def build(source_rows):
    return {name: [(row['id'], cls(SourceStore(row))) for row in source_rows]
            for name, cls in [('offset', EvidenceGraph), ('quote', QuoteGraph)]}


def export(path, arms, protocol, *, stage='initial'):
    requests = {}
    for arm, graphs in arms.items():
        for cid, graph in graphs:
            jobs = graph.initial_jobs() if stage == 'initial' else graph.pending_jobs()
            for job in jobs:
                wire = body(job, protocol['model_id'])
                key = digest(wire)
                entry = requests.setdefault(key, {'request_sha256': key, 'task': job['task'],
                    'wire_body': wire, 'uses': []})
                entry['uses'].append({'arm': arm, 'case_id': cid, 'job_id': job['id']})
    entries = sorted(requests.values(), key=lambda r: (r['task'] != 'EFFECT', r['request_sha256']))
    if stage != 'initial':
        raw_dir = path.parent / 'raw'
        entries = [r for r in entries if not (raw_dir / (r['request_sha256'] + '.json')).exists()]
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in entries),
                    encoding='utf-8', newline='\n')
    write(path.with_suffix('.seal.json'), {'queue_sha256': sha(path),
          'protocol_sha256': protocol['protocol_sha256'], 'requests': len(entries),
          'by_task': dict(Counter(r['task'] for r in entries))})
    return {'requests': len(entries), 'by_task': dict(Counter(r['task'] for r in entries))}


def prepare(args):
    if (args.out / 'protocol.json').exists():
        raise ValueError('OUTPUT_ALREADY_FROZEN')
    args.out.mkdir(parents=True, exist_ok=True)
    inputs = args.out / 'inputs.jsonl'
    source_rows = rows(args.inputs)
    inputs.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in source_rows),
                      encoding='utf-8', newline='\n')
    protocol = {'version': 'evidence-graph-paired-address-probe/1',
        'source_code': fingerprints(), 'input_sha256': sha(inputs),
        'model_id': args.model, 'pydantic_version': pydantic.__version__,
        'limits': {'http': 300, 'tokens': 1500000}, 'timeout': 180,
        'historical_expenses': {'v11_http': 449, 'known_tokens': 2196864,
                               'unknown_tokens_upper_bound': 159110,
                               'note': 'Previous phase retained; new phase has separate ledger.'},
        'authorization': 'User 2026-10-04 explicitly authorized new API experiments.',
        'data_status': 'PREVIOUSLY_SEEN_PUBLIC_INPUTS_NO_GOLD_READ',
        'arms': {'offset': 'Unchanged source-window graph/1 integer-offset prompts.',
                 'quote': 'Same semantic task; exact quotes, uniquely code-resolved.'},
        'selection': 'All 46 input rows and all initial requests; no outcome-based selection.',
        'stop': 'First HTTP or transport error; no retries or repair prompts.',
        'promotion': 'SHADOW_ONLY; scripts/predict.py unchanged.',
        'metrics': ['schema_and_source_admission', 'per_task_failure_causes',
                    'requirements_proposed_and_open', 'per_target_open_causes'],
        'limitations': ['No gold completeness measurement', 'Source validity is not semantic proof',
                         'Historical actions and text-only responses not evaluated as targets']}
    protocol['protocol_sha256'] = digest(protocol)
    write(args.out / 'protocol.json', protocol)
    count = export(args.out / 'initial.jsonl', build(source_rows), protocol)
    write(args.out / 'preparation.json', count)
    return count


def verify(out):
    protocol = json.loads((out / 'protocol.json').read_text(encoding='utf-8'))
    if digest({k: v for k, v in protocol.items() if k != 'protocol_sha256'}) != protocol['protocol_sha256']:
        raise ValueError('PROTOCOL_CHANGED')
    if protocol['source_code'] != fingerprints() or protocol['pydantic_version'] != pydantic.__version__:
        raise ValueError('FROZEN_CODE_OR_SCHEMA_GENERATOR_CHANGED')
    if sha(out / 'inputs.jsonl') != protocol['input_sha256']:
        raise ValueError('INPUT_CHANGED')
    return protocol


def replay(args):
    protocol = verify(args.out)
    arms = build(rows(args.out / 'inputs.jsonl'))
    raw = {}
    for path in sorted((args.out / 'raw').glob('*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        if record['protocol_sha256'] != protocol['protocol_sha256'] or record['model_id'] != protocol['model_id']:
            raise ValueError('CACHE_PROTOCOL_OR_MODEL_MISMATCH')
        raw[record['request_sha256']] = record
    admissions = []
    for arm, graphs in arms.items():
        for cid, graph in graphs:
            for _ in range(8):
                progress = False
                for job in graph.pending_jobs():
                    request_sha = digest(body(job, protocol['model_id']))
                    record = raw.get(request_sha)
                    if not record:
                        continue
                    parsed = None
                    if record['status'] == 'OK':
                        choice = record['provider_response'].get('choices', [{}])[0]
                        content = choice.get('message', {}).get('content')
                        if isinstance(content, str):
                            parsed, valid = decode_json(content)
                            if not valid:
                                parsed = None
                        if choice.get('finish_reason') != 'stop':
                            parsed = None
                    if not isinstance(parsed, dict):
                        result = {'valid': False, 'cause': 'PROVIDER_INVALID_OR_UNFINISHED_JSON'}
                        graph.failures[job['id']] = {'task': job['task'], 'key': job['key'], **result}
                    else:
                        result = graph.admit(job['id'], parsed)
                    admissions.append({'arm': arm, 'case_id': cid, 'job_id': job['id'],
                        'request_sha256': request_sha, 'task': job['task'], **result})
                    progress = True
                if not progress:
                    break
    write(args.out / 'admissions.json', admissions)
    summary = {}
    for arm, graphs in arms.items():
        reports = [{'id': cid, **graph.report()} for cid, graph in graphs]
        write(args.out / (arm + '_reports.json'), reports)
        write(args.out / (arm + '_extracted.json'), [{'id': cid,
            'inventories': graph.inventories, 'effects': graph.effects,
            'requirements': graph.requirements, 'links': [v for v in graph.links.values()],
            'witnesses': [v for replies in graph.witnesses.values() for v in replies]}
            for cid, graph in graphs])
        unique = {(a['request_sha256'], a['task']): a for a in admissions if a['arm'] == arm}
        summary[arm] = {'unique_responses': len(unique),
            'admitted_by_task': dict(Counter(a['task'] for a in unique.values() if a['valid'])),
            'failed_by_task': dict(Counter(a['task'] for a in unique.values() if not a['valid'])),
            'failure_causes': dict(Counter(a['cause'] for a in unique.values() if not a['valid'])),
            'requirements_logical': sum(len(graph.requirements) for _, graph in graphs),
            'candidate_decisions': dict(Counter(target['candidate_decision']
                 for r in reports for target in r['targets'])),
            'semantic_completeness_proven': False}
    write(args.out / 'score.json', summary)
    if args.export_next:
        summary['next'] = export(args.out / args.export_next, arms, protocol, stage='pending')
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['prepare', 'replay'])
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--inputs', type=Path, default=ROOT / 'outputs/searh_23/evidence_graph_v1_sealed/inputs.jsonl')
    p.add_argument('--model', default='ministral-14b-latest')
    p.add_argument('--export-next')
    args = p.parse_args()
    print(json.dumps(prepare(args) if args.phase == 'prepare' else replay(args), ensure_ascii=False))

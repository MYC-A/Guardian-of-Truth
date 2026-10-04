"""Prepare/freeze and replay model files. This program has NO HTTP execution mode.

Raw replies must carry the frozen protocol hash and exact request hash. Old
consent answers cannot be substituted for new graph requests. Missing replies
remain UNKNOWN. The public inputs are already seen development material.
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

from guardian_truth.evidence_graph import EvidenceGraph
from guardian_truth.parsing import decode_json
from guardian_truth.source_search.store import SourceStore, digest


DEFAULT_INPUT = ROOT / 'outputs/searh_23/source_search_20261002/comparison_ids_v5/inputs.jsonl'
DEFAULT_OUT = ROOT / 'outputs/searh_23/evidence_graph_v1_sealed'


def read(path):
    obj, valid = decode_json(Path(path).read_text(encoding='utf-8'))
    if not valid:
        raise ValueError('Invalid or duplicate-key JSON: ' + str(path))
    return obj


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    tmp.replace(path)


def rows(path):
    result = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        row, valid = decode_json(line)
        if not valid or not isinstance(row, dict) or set(row) != {'id', 'prompt', 'response'}:
            raise ValueError('Input must contain exactly id/prompt/response and no labels')
        if any(not isinstance(v, str) for v in row.values()):
            raise ValueError('Input values must be text')
        result.append(row)
    if len({r['id'] for r in result}) != len(result):
        raise ValueError('Duplicate case ID')
    return result


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_source_sha(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def code_fingerprint():
    # Capture all imported package code, including the existing parser/provenance.
    files = list((ROOT / 'src/guardian_truth').rglob('*.py'))
    files += [Path(__file__), ROOT / 'tests/test_evidence_graph.py']
    return {p.relative_to(ROOT).as_posix(): canonical_source_sha(p) for p in sorted(files)}


def request_hash(job):
    return digest({'messages': job['messages'], 'response_format': job['response_format']})


def export_jobs(path, graphs, *, bidirectional=True):
    requests = {}
    count = 0
    for case_id, graph in graphs:
        for job in graph.pending_jobs(bidirectional=bidirectional):
            key = request_hash(job)
            entry = requests.setdefault(key, {'request_sha256': key, 'task': job['task'],
                'messages': job['messages'], 'response_format': job['response_format'], 'uses': []})
            entry['uses'].append({'case_id': case_id, 'job_id': job['id']})
            count += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as file:
        for entry in requests.values():
            file.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + '\n')
    return {'logical_jobs': count, 'unique_requests': len(requests),
            'by_task': dict(Counter(r['task'] for r in requests.values()))}


def prepare(args):
    out = args.out
    source_rows = rows(args.inputs)
    if (out / 'protocol.json').exists():
        raise ValueError('Frozen output already exists; choose a new directory')
    out.mkdir(parents=True, exist_ok=True)
    inputs = out / 'inputs.jsonl'
    inputs.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in source_rows), encoding='utf-8', newline='\n')
    options = {'chunk_chars': args.chunk_chars, 'witness_sources': 8, 'max_rereads': 2,
               'strategy': args.strategy}
    graphs = [(r['id'], EvidenceGraph(SourceStore(r), **options)) for r in source_rows]
    inventory = [{'id': cid, **g.report()} for cid, g in graphs]
    counts = export_jobs(out / 'initial_requests.jsonl', graphs)
    protocol = {'version': EvidenceGraph.VERSION, 'source_code': code_fingerprint(),
        'input_sha256': sha(inputs), 'options': options, 'cases': len(graphs),
        'targets': sum(len(g.targets) for _, g in graphs), 'initial_requests': counts,
        'model_id': args.model, 'status': 'PREPARED_NO_MODEL_INFERENCE',
        'pydantic_version': pydantic.__version__,
        'code_hash_format': 'CRLF_NORMALIZED_TO_LF; INPUT_CHARACTERS_UNCHANGED',
        'data_status': 'PREVIOUSLY_SEEN_PUBLIC_INPUTS_NOT_HELD_OUT',
        'target_scope': 'CURRENT_NATIVE_TOOL_CALLS; HISTORY_AS_EVIDENCE; SPEECH_NOT_EVALUATED',
        'semantic_completeness_proven': False, 'new_http_attempts': 0,
        'ablation': 'Same inventoried requirements; forward top-4 versus full reverse links',
        'schema_note': 'Exported JSON schema needs provider support; admission alone is not constrained decoding',
        'declaration_extent': 'PARSED_RANGE_MAY_INCLUDE_TRAILING_POLICY_NOT_SEMANTICALLY_VERIFIED',
        'stop_rule': 'NO_NETWORK_MODE_IMPLEMENTED; new API calls require renewed authorization'}
    protocol['protocol_sha256'] = digest(protocol)
    write(out / 'protocol.json', protocol)
    write(out / 'inventory.json', inventory)
    summary = {'cases': len(graphs), 'targets': protocol['targets'],
        'policy_windows': sum(len(g.units) for _, g in graphs),
        'all_system_characters_preserved': all(g.report()['source_span_coverage'] == 1 for _, g in graphs),
        **counts, 'new_http_attempts': 0, 'model_quality_measured': False}
    write(out / 'preparation_summary.json', summary)
    return summary


def verify(out):
    protocol = read(out / 'protocol.json')
    expected = protocol['protocol_sha256']
    if digest({k: v for k, v in protocol.items() if k != 'protocol_sha256'}) != expected:
        raise ValueError('Protocol hash changed')
    if pydantic.__version__ != protocol['pydantic_version']:
        raise ValueError('Pydantic version differs from frozen schema generator')
    if sha(out / 'inputs.jsonl') != protocol['input_sha256'] or code_fingerprint() != protocol['source_code']:
        raise ValueError('Frozen input or source code changed; prepare a new protocol')
    return protocol


def replay(args):
    out = args.out
    protocol = verify(out)
    cache = {}
    if args.cache:
        for path in sorted(args.cache.glob('*.json')):
            record = read(path)
            if (set(record) != {'protocol_sha256', 'request_sha256', 'model_id', 'reply'}
                    or record['protocol_sha256'] != protocol['protocol_sha256']
                    or record['model_id'] != protocol['model_id']):
                raise ValueError('Reply protocol/model mismatch: ' + path.name)
            key = record['request_sha256']
            if key in cache:
                raise ValueError('Duplicate request in cache')
            cache[key] = record['reply']
    graphs = [(r['id'], EvidenceGraph(SourceStore(r), **protocol['options'])) for r in rows(out / 'inputs.jsonl')]
    used = set()
    for _ in range(8):
        progress = False
        for _, g in graphs:
            for job in g.pending_jobs(bidirectional=args.arm == 'bidirectional'):
                key = request_hash(job)
                if key in cache:
                    g.admit(job['id'], cache[key])
                    used.add(key)
                    progress = True
        if not progress:
            break
    result_path = out / ('replay_' + args.arm)
    reports = [{'id': cid, **g.report()} for cid, g in graphs]
    write(result_path / 'reports.json', reports)
    pending = export_jobs(result_path / 'pending_requests.jsonl', graphs, bidirectional=args.arm == 'bidirectional')
    decisions = Counter(t['candidate_decision'] for r in reports for t in r['targets'])
    summary = {'protocol_sha256': protocol['protocol_sha256'], 'model_id': protocol['model_id'],
        'arm': args.arm, 'cases': len(graphs), 'targets': sum(len(g.targets) for _, g in graphs),
        'cached_requests_admitted_or_rejected': len(used), 'unused_cache_entries': len(set(cache) - used),
        'candidate_decisions': dict(decisions), 'pending': pending,
        'failed_jobs': sum(len(g.failures) for _, g in graphs), 'new_http_attempts': 0,
        'model_quality_measured': False, 'mode': 'SHADOW_ONLY_NO_GOLD_READ'}
    write(result_path / 'summary.json', summary)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['prepare', 'replay'])
    p.add_argument('--inputs', type=Path, default=DEFAULT_INPUT)
    p.add_argument('--out', type=Path, default=DEFAULT_OUT)
    p.add_argument('--cache', type=Path)
    p.add_argument('--arm', choices=['forward', 'bidirectional'], default='bidirectional')
    p.add_argument('--chunk-chars', type=int, default=2400)
    p.add_argument('--strategy', choices=['BFS', 'DFS'], default='BFS')
    p.add_argument('--model', default='NOT_SELECTED_NO_API_AUTHORIZATION')
    args = p.parse_args()
    print(json.dumps(prepare(args) if args.phase == 'prepare' else replay(args), ensure_ascii=False))


if __name__ == '__main__':
    main()

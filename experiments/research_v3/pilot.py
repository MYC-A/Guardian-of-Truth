"""Frozen A0/A1/A2/A3 pilot. prepare/replay never access the network or gold.

run uses bounded one-attempt HTTP with credentials only in memory. Gold is
opened exclusively by the separate scorer after prediction files are written.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).parent))
import pydantic
from contracts import Direct, Discovery, Lowering, PROMPTS
from guardian_truth.evidence_graph import EvidenceGraph
from guardian_truth.evidence_graph.facts import compare
from guardian_truth.evidence_graph.graph import all_leaves
from guardian_truth.evidence_graph.logic import evaluate_requirement
from guardian_truth.evidence_graph.schema import Formula
from guardian_truth.parsing import decode_json
from guardian_truth.source_search.store import SourceStore, digest

HERE = Path(__file__).parent
DEFAULT_OUT = ROOT / 'outputs/searh_23/semantic_hybrid_v4_20261004'
ENDPOINTS = {'mistral': 'https://api.mistral.ai/v1/chat/completions',
             'ollama': 'https://ollama.com/v1/chat/completions',
             'ukisai': 'https://ukisai.com/api/swift/v1/chat/completions',
             'vireonix': 'https://vireonix.ai/v1/chat/completions'}


def read(path):
    value, valid = decode_json(Path(path).read_text(encoding='utf-8'))
    if not valid:
        raise ValueError('INVALID_OR_DUPLICATE_JSON')
    return value


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def inputs(path):
    rows = [json.loads(s) for s in Path(path).read_text(encoding='utf-8').splitlines()]
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('DUPLICATE_CASE')
    return rows


def fingerprints():
    paths = sorted(list(HERE.glob('*.py')) + list((ROOT / 'src/guardian_truth').rglob('*.py')))
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}


def prepare(args):
    if (args.out / 'protocol.json').exists():
        raise ValueError('FROZEN_OUTPUT_EXISTS')
    source_inputs = HERE / 'fixtures/inputs.jsonl'
    source_gold = HERE / 'fixtures/gold.json'
    args.out.mkdir(parents=True)
    # Gold hash is sealed but gold content never enters the inference packet.
    rows = inputs(source_inputs)
    protocol = dict(version='semantic-hybrid-v4/1', base_sha='1980776e64190cdcd4017302b10f80d04b5ad735',
                    source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                    source_code=fingerprints(), input_sha256=sha(source_inputs), gold_sha256=sha(source_gold),
                    pydantic_version=pydantic.__version__, provider=args.provider, model=args.model,
                    arms=['A0', 'A1', 'A2', 'A3'], temperature=0, timeout=120,
                    max_tokens=3500, graph_inventory_tokens=7000, graph_rounds=8,
                    limits={'http': 360, 'tokens': 1000000},
                    data_status='AUTHOR_CONTROLLED_NEW_FAMILY_HOLDOUT_NOT_EXTERNAL_BLINDED',
                    unknown_binary_mapping=0, production_promotion=False,
                    policy_completeness_proven=False)
    protocol['protocol_sha256'] = digest(protocol)
    write(args.out / 'protocol.json', protocol)
    write(args.out / 'preparation.json', {'cases': len(rows), 'native_first_targets': sum(bool(make_graph(r).targets) for r in rows),
                                        'gold_read_during_inference': False, 'http_attempts': 0})
    return protocol


def verify(out):
    p = read(out / 'protocol.json')
    if p['protocol_sha256'] != digest({k: v for k, v in p.items() if k != 'protocol_sha256'}):
        raise ValueError('PROTOCOL_CHANGED')
    if p['source_code'] != fingerprints() or p['input_sha256'] != sha(HERE / 'fixtures/inputs.jsonl'):
        raise ValueError('FROZEN_SOURCE_OR_INPUT_CHANGED')
    if p['pydantic_version'] != pydantic.__version__:
        raise ValueError('SCHEMA_GENERATOR_VERSION_CHANGED')
    return p


def make_graph(row):
    return EvidenceGraph(SourceStore({'prompt': row['prompt'], 'response': row['response']}))


def registry(row, graph):
    records = {}
    system_id = next(sid for sid, s in graph.store.sources.items() if s['role'] == 'system')
    system = graph.store.text(system_id)
    cursor = 0
    for i, section in enumerate(row['policy_sections']):
        start = system.index(section, cursor)
        records['p' + str(i)] = dict(kind='policy', text=section,
                                    span={'source_id': system_id, 'start': start, 'end': start + len(section)})
        cursor = start + len(section)
    for name, sid in graph.declarations.items():
        records[sid] = dict(kind='declaration', tool=name, text=graph.text(sid),
                            span={'source_id': sid, 'start': 0, 'end': len(graph.text(sid))})
    for sid, source in graph.store.sources.items():
        if source['kind'] == 'raw' or source['role'] == 'system':
            continue
        events = graph.store.history_events if source['document'] == 'prompt' else graph.store.target_events
        event = events[source['event']]
        records[sid] = dict(kind=source['kind'], role=source['role'], document=source['document'],
                            text=graph.store.text(sid), native_json=event.value if event.json_valid else None,
                            span={'source_id': sid, 'start': 0, 'end': len(graph.store.text(sid))})
    literals = {}
    # Generic JSON scalar lexemes; no business predicates or field-name mappings.
    for match in re.finditer(r'(?<![\w.-])(?:true|false|null|-?\d+(?:\.\d+)?)(?![\w.-])', system):
        value, valid = decode_json(match.group())
        if valid:
            lid = 'k' + str(len(literals))
            literals[lid] = {'value': value, 'span': {'source_id': system_id, 'start': match.start(), 'end': match.end()}}
    target_id = next(iter(graph.targets), next((sid for sid, s in records.items() if s.get('document') == 'response'), None))
    return {'sources': records, 'policy_literals': literals,
            'target_id': target_id, 'target': graph.targets.get(target_id) or {'source_id': target_id, 'kind': 'speech'},
            'source_sha256': graph.store.source_sha256}


def packet(reg, *, target=True):
    r = deepcopy(reg)
    if not target:
        r.pop('target_id'); r.pop('target'); r.pop('source_sha256')
        r['sources'] = {sid: s for sid, s in r['sources'].items() if s['kind'] in ('policy', 'declaration')}
    # Code offsets are never generated by the source-ID model.
    for s in r['sources'].values():
        s.pop('span', None)
    for s in r['policy_literals'].values():
        s.pop('span', None)
    return r


def source_ids(reply):
    found = []
    def visit(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ('policy_ids', 'source_ids', 'exception_ids', 'declaration_ids', 'evidence_ids'):
                    found.extend(v)
                else:
                    visit(v)
        elif isinstance(x, list):
            for v in x:
                visit(v)
    visit(reply)
    return found


def admit(schema, data, reg):
    reply = schema.model_validate(data).model_dump()
    if any(sid not in reg['sources'] for sid in source_ids(reply)):
        raise ValueError('UNKNOWN_SOURCE_ID')
    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ('policy_ids', 'exception_ids') and any(reg['sources'][sid]['kind'] != 'policy' for sid in v):
                    raise ValueError('POLICY_ID_HAS_WRONG_ROLE')
                if k == 'declaration_ids' and any(reg['sources'][sid]['kind'] != 'declaration' for sid in v):
                    raise ValueError('DECLARATION_ID_HAS_WRONG_ROLE')
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(reply)
    return reply


def lower_tree(tree, reg):
    if any(reg['sources'][sid]['kind'] != 'policy' for sid in tree['source_ids']):
        raise ValueError('FORMULA_CITES_NON_POLICY_SOURCE')
    t = {'op': tree['op'], 'label': tree['label'],
         'spans': [reg['sources'][sid]['span'] for sid in tree['source_ids']],
         'children': [lower_tree(c, reg) for c in tree['children']]}
    return Formula.model_validate(t).model_dump()


def native_check(check, graph, reg):
    def native(sid, pointer):
        return {'kind': 'NATIVE_JSON', 'source_id': sid, 'pointer': pointer, 'literal_span': None}
    if check['literal_id'] is not None:
        if check['rhs_source'] is not None or check['rhs_pointer'] is not None:
            raise ValueError('AMBIGUOUS_RHS')
        span = reg['policy_literals'][check['literal_id']]['span']
        rhs = {'kind': 'SOURCE_LITERAL', 'source_id': span['source_id'], 'pointer': None, 'literal_span': span}
    else:
        rhs = native(check['rhs_source'], check['rhs_pointer'])
    if reg['target_id'] not in graph.targets:
        return {'value': 'UNKNOWN', 'cause': 'PROSE_NATIVE_COMPARISON_NOT_SUPPORTED_BY_CALL_RUNTIME'}
    return compare(graph, reg['target_id'], {'lhs': native(check['lhs_source'], check['lhs_pointer']),
                    'operator': check['operator'], 'rhs': rhs, 'bindings': check['bindings']})


def evaluate_local(reply, graph, reg):
    results, opened, checks = [], list(reply['missing']), []
    if reply['effect'] == 'UNKNOWN':
        opened.append('ACTION_EFFECT_UNRESOLVED')
    used = []
    for norm in reply['requirements']:
        used.extend(norm['policy_ids'])
        if norm['applies'] == 'NO':
            continue
        if norm['applies'] == 'UNRESOLVED':
            opened.append('APPLICABILITY_UNRESOLVED'); continue
        required = {'local_id': norm['local_id'], 'action': norm['action'], 'scope': 'current target',
                    'modality': norm['modality'], 'condition': lower_tree(norm['condition'], reg),
                    'guard': lower_tree(norm['guard'], reg) if norm['guard'] else None,
                    'exceptions': [lower_tree(t, reg) for t in norm['exceptions']],
                    'open_questions': norm['open_questions']}
        leaves = {path for path, _ in all_leaves(required)}
        witnesses = {}
        for witness in norm['witnesses']:
            if witness['path'] not in leaves or witness['path'] in witnesses:
                raise ValueError('UNKNOWN_OR_DUPLICATE_WITNESS_PATH')
            value = witness['value']
            if value != 'UNKNOWN' and not witness['evidence_ids']:
                value = 'UNKNOWN'
            if witness['check']:
                factual = native_check(witness['check'], graph, reg)
                checks.append({'requirement': norm['local_id'], 'path': witness['path'], **factual})
                value = factual['value']
            elif (witness['position_source_id'] is not None and
                  witness['position_source_id'] in witness['evidence_ids'] and
                  reg['sources'][witness['position_source_id']]['kind'] == 'call' and
                  reg['sources'][witness['position_source_id']].get('role') == 'assistant'):
                # A native call proves an attempted occurrence, not successful effect.
                # This supports chronology of calls under a model-selected action.
                value = 'TRUE' if witness['position_source_id'] in graph._allowed_prior(reg['target_id']) else 'UNKNOWN'
            elif any(reg['sources'][sid]['kind'] in ('call', 'result') for sid in witness['evidence_ids']):
                # A model cannot bypass deterministic JSON checking by leaving check null.
                value = 'UNKNOWN'
                checks.append({'requirement': norm['local_id'], 'path': witness['path'],
                               'value': 'UNKNOWN', 'cause': 'NATIVE_EVIDENCE_REQUIRES_CHECK'})
            pos = None
            sid = witness['position_source_id']
            if sid is not None and reg['target_id'] in graph.targets:
                prior = graph._allowed_prior(reg['target_id'])
                if sid in prior and sid in witness['evidence_ids'] and graph.refs[sid]['role'] == 'assistant' and graph.refs[sid]['kind'] == 'call':
                    pos = prior.index(sid)
            witnesses[witness['path']] = {'value': value, 'position': pos, 'reason': witness['reason']}
        evaluation = evaluate_requirement(required, witnesses)
        results.append({'id': norm['local_id'], 'policy_ids': norm['policy_ids'], **evaluation})
        if evaluation['status'] == 'UNKNOWN':
            opened.extend(o['cause'] for o in evaluation['open'])
            if not evaluation['open']:
                opened.append('REQUIREMENT_UNRESOLVED')
    verdict = 'ERROR' if any(r['status'] == 'VIOLATED' for r in results) else 'UNKNOWN' if opened else 'NO_ERROR'
    return {'verdict': verdict, 'effect': reply['effect'], 'requirements': results,
            'policy_ids': sorted(set(used)), 'open': opened, 'native_checks': checks,
            'assurance': 'MODEL_SEMANTICS_WITH_CODE_CHECKED_FACTS', 'code_proof': False}


def credentials(provider):
    name = provider.upper() + '_API_KEY'
    env = {}
    for path in [Path('/workspace/.env'), Path('/workspace/guardian/secrets/mistral.env'),
                 Path('/workspace/guardian/secrets/api_keys.env')]:
        if path.is_file():
            for s in path.read_text().splitlines():
                s = s.strip().removeprefix('export ')
                if '=' in s and not s.startswith('#'):
                    k, v = s.split('=', 1)
                    if k.strip() == name:
                        env[name] = v.strip().strip('"').strip("'")
    return os.environ.get(name) or env.get(name) or ('none' if provider in ('ukisai', 'vireonix') else None)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, out, protocol, live):
        self.out, self.p, self.live = out, protocol, live
        self.ledger = read(out / 'ledger.json') if (out / 'ledger.json').exists() else {}
        self.uses = []
        self.breaker = any(v['status'] != 'OK' for v in self.ledger.values())

    def ask(self, task, packet_value, schema=None, job=None):
        if job:
            messages, response_format = job['messages'], job['response_format']
            maximum = self.p['graph_inventory_tokens'] if task == 'INVENTORY' else self.p['max_tokens']
        else:
            messages = [{'role': 'system', 'content': PROMPTS[task]},
                        {'role': 'user', 'content': json.dumps(packet_value, ensure_ascii=False)}]
            response_format = {'type': 'json_schema', 'json_schema': {'name': 'reply', 'strict': True,
                               'schema': schema.model_json_schema()}}
            maximum = self.p['max_tokens']
        body = {'model': self.p['model'], 'messages': messages, 'temperature': 0,
                'max_tokens': maximum, 'response_format': response_format}
        key = digest({'endpoint': ENDPOINTS[self.p['provider']], 'body': body})
        self.uses.append({'task': task, 'request_sha256': key})
        raw_path = self.out / 'raw' / (key + '.json')
        if raw_path.exists():
            record = read(raw_path)
            if record['request_sha256'] != key or record['protocol_sha256'] != self.p['protocol_sha256']:
                raise ValueError('CACHE_IDENTITY_MISMATCH')
        else:
            if not self.live or self.breaker:
                return None, {'cause': 'CACHE_MISS_OR_BREAKER', 'request_sha256': key}
            # Durable one-attempt reservation precedes HTTP. Unknown usage remains
            # conservatively charged, including interrupted requests.
            if key in self.ledger:
                self.breaker = True
                return None, {'cause': 'PRIOR_UNSAVED_ATTEMPT_NO_RETRY', 'request_sha256': key}
            bound = len(json.dumps(body, ensure_ascii=False).encode()) + maximum
            charged = sum(v['charged_tokens'] for v in self.ledger.values())
            if len(self.ledger) >= self.p['limits']['http'] or charged + bound > self.p['limits']['tokens']:
                return None, {'cause': 'BUDGET_STOP', 'request_sha256': key}
            secret = credentials(self.p['provider'])
            if not secret:
                self.breaker = True
                return None, {'cause': 'CREDENTIAL_UNAVAILABLE', 'request_sha256': key}
            self.ledger[key] = {'status': 'RESERVED', 'charged_tokens': bound, 'task': task}
            write(self.out / 'ledger.json', self.ledger)
            write(self.out / 'requests' / (key + '.json'), {'request_sha256': key, 'endpoint_category': self.p['provider'],
                  'prompt_sha256': digest(messages), 'body': body})
            record = {'protocol_sha256': self.p['protocol_sha256'], 'request_sha256': key, 'task': task}
            started = time.monotonic()
            try:
                request = urllib.request.Request(ENDPOINTS[self.p['provider']], data=json.dumps(body).encode(),
                           headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + secret})
                with urllib.request.build_opener(NoRedirect()).open(request, timeout=self.p['timeout']) as response:
                    raw = response.read().decode('utf-8')
                    data, valid = decode_json(raw)
                    if not valid:
                        raise ValueError('INVALID_PROVIDER_JSON')
                record.update(status='OK', provider_response=data)
            except urllib.error.HTTPError as e:
                record.update(status='HTTP_ERROR', http_status=e.code)
                self.breaker = True
            except Exception as e:
                record.update(status='TRANSPORT_ERROR', error_type=type(e).__name__)
                self.breaker = True
            record['seconds'] = time.monotonic() - started
            tokens = record.get('provider_response', {}).get('usage', {}).get('total_tokens')
            known = type(tokens) is int and tokens >= 0
            record.update(known_tokens=tokens if known else 0, charged_tokens=tokens if known else bound,
                          unknown_usage=not known)
            write(raw_path, record)
            self.ledger[key] = {k: record[k] for k in ('status', 'charged_tokens', 'task', 'seconds', 'known_tokens')}
            write(self.out / 'ledger.json', self.ledger)
            print(json.dumps({'task': task, 'status': record['status'], 'attempts': len(self.ledger),
                              'tokens': sum(v.get('known_tokens', 0) for v in self.ledger.values())}), flush=True)
        meta = {k: record.get(k) for k in ('request_sha256', 'status', 'seconds', 'known_tokens')}
        if record['status'] != 'OK':
            return None, {**meta, 'cause': record['status']}
        choice = record['provider_response'].get('choices', [{}])[0]
        text = choice.get('message', {}).get('content')
        data, valid = decode_json(text) if isinstance(text, str) else (None, False)
        if choice.get('finish_reason') != 'stop' or not valid or not isinstance(data, dict):
            return None, {**meta, 'cause': 'UNFINISHED_OR_INVALID_REPLY'}
        return data, meta


def infer(args):
    protocol = verify(args.out)
    client = Client(args.out, protocol, args.phase == 'run')
    rows = inputs(HERE / 'fixtures/inputs.jsonl')
    predictions = []
    for row in rows:
        g, observations = make_graph(row), []
        reg = registry(row, g)
        source_packet = packet(reg)
        shared = None
        for arm in args.arms:
            start_uses = len(client.uses)
            result = {'verdict': 'UNKNOWN'}
            failure = None
            try:
                if arm == 'A1':
                    if not g.targets:
                        result = {'verdict': 'UNKNOWN', 'scope_excluded': True}
                    else:
                        for _ in range(protocol['graph_rounds']):
                            jobs = g.pending_jobs()
                            if not jobs:
                                break
                            progress = False
                            for job in jobs:
                                data, meta = client.ask(job['task'], None, job=job)
                                observations.append(meta)
                                if data is not None:
                                    admission = g.admit(job['id'], data)
                                    observations[-1]['admission'] = admission
                                    progress = True
                            if not progress:
                                break
                        report = g.report()
                        # The common target is the FIRST current native call.
                        first = report['targets'][0]
                        result = {'verdict': first['candidate_decision'], 'graph_report': report,
                                  'policy_ids': [], 'effect': g.effects.get(first['tool'], {}).get('effect', 'UNKNOWN')}
                elif arm == 'A0':
                    data, meta = client.ask('A0', source_packet, Direct)
                    observations.append(meta)
                    if data is None:
                        failure = meta['cause']
                    else:
                        result = admit(Direct, data, reg)
                else:
                    if shared is None:
                        data, meta = client.ask('DISCOVER', packet(reg, target=False), Discovery)
                        observations.append(meta)
                        if data is not None:
                            shared = admit(Discovery, data, reg)
                    if shared is None:
                        failure = 'FORWARD_DISCOVERY_UNAVAILABLE'
                    else:
                        candidates = deepcopy(shared['candidates'])
                        reverse = None
                        if arm == 'A3':
                            data, meta = client.ask('REVERSE', source_packet, Discovery)
                            observations.append(meta)
                            if data is not None:
                                reverse = admit(Discovery, data, reg)
                                # Union source hypotheses, never verdicts or formulas.
                                identities = {digest(c) for c in candidates}
                                for c in reverse['candidates']:
                                    if digest(c) not in identities:
                                        candidates.append(c); identities.add(digest(c))
                        data, meta = client.ask('LOWER', {**source_packet, 'candidates': candidates}, Lowering)
                        observations.append(meta)
                        if data is None:
                            failure = meta['cause']
                        else:
                            lowered = admit(Lowering, data, reg)
                            result = evaluate_local(lowered, g, reg)
                            result.update(forward=shared, reverse=reverse, lowered=lowered)
                            if arm == 'A3' and reverse is None:
                                result['reverse_missing'] = True
            except (ValueError, KeyError, TypeError) as e:
                failure = type(e).__name__ + ':' + str(e)[:1500]
                result = {'verdict': 'UNKNOWN'}
            predictions.append({'id': row['id'], 'arm': arm, 'failure': failure,
                                'result': result, 'requests': client.uses[start_uses:], 'observations': deepcopy(observations)})
            write(args.out / ('predictions_' + '_'.join(args.arms) + '.json'), predictions)
            print(json.dumps({'case': row['id'], 'arm': arm, 'verdict': result['verdict'], 'failure': failure}), flush=True)
            observations = []
    write(args.out / ('completion_' + '_'.join(args.arms) + '.json'),
          {'mode': args.phase, 'predictions': len(predictions), 'attempts': len(client.ledger),
           'known_tokens': sum(v.get('known_tokens', 0) for v in client.ledger.values()), 'breaker': client.breaker,
           'gold_read': False, 'protocol_sha256': protocol['protocol_sha256']})
    return {'predictions': len(predictions), 'attempts': len(client.ledger), 'breaker': client.breaker}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['prepare', 'run', 'replay'])
    p.add_argument('--out', type=Path, default=DEFAULT_OUT)
    p.add_argument('--model', default='ministral-14b-latest')
    p.add_argument('--provider', choices=ENDPOINTS, default='mistral')
    p.add_argument('--arms', nargs='+', choices=['A0', 'A1', 'A2', 'A3'], default=['A0', 'A1', 'A2', 'A3'])
    args = p.parse_args()
    print(json.dumps(prepare(args) if args.phase == 'prepare' else infer(args), ensure_ascii=False))

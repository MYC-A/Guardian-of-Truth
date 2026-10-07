"""Paired runtime replay using exact saved request identities. No network or gold input to runtime."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import socket
import sys
import subprocess

sys.dont_write_bytecode = True
ap = argparse.ArgumentParser()
ap.add_argument('--runtime-root', type=Path, required=True)
ap.add_argument('--output', type=Path, required=True)
ap.add_argument('--arms', nargs='+', default=['R_fix', 'R_comb'])
ap.add_argument('--sets', nargs='+')
ap.add_argument('--reps', type=int, nargs='+')
args = ap.parse_args()
ROOT = args.runtime_root.resolve()
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
runtime_files = sorted((ROOT / 'src/guardian_truth').rglob('*.py')) + sorted((ROOT / 'experiments/universal_repair').glob('*.py'))
def runtime_fingerprints():
    return {str(path.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest() for path in runtime_files}
runtime_before = runtime_fingerprints()
runtime_head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def forbidden(*a, **k):
    raise RuntimeError('REPLAY_NETWORK_FORBIDDEN')


socket.create_connection = forbidden
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden

from guardian_truth.integrated.transport import sha
from guardian_truth.repair.clients import ReadThrough
from guardian_truth.repair.v5 import ARMS, run_v5, decide
from guardian_truth.repair.records import load
from experiments.universal_repair.run import inputs
from experiments.universal_repair.score import gold_for

RUNS = [('valid46', 1), ('valid46', 2), ('valid46', 3), ('lb_long', 1), ('lb2_long', 1),
        ('lb3_long', 1), ('lb3_long', 2), ('ext_tau2', 1), ('ext_tau2', 2), ('ext_tau2', 3),
        ('hold_tau2h', 1), ('hold_tau2h', 2), ('hold_tau2h', 3), ('hold_holdout2', 1), ('hold_holdout2', 2)]
FROZEN = [ROOT / p for p in ('outputs/verification_v2/cache/mistral', 'outputs/universal_repair/cache/mistral',
                            'outputs/universal_repair_v2/cache/mistral')]


class CaseClient:
    def __init__(self, record):
        self.fallback = ReadThrough('mistral', 'ministral-14b-2512', FROZEN)
        self.saved, self.calls, self.missing = {}, Counter(), []
        self.collect(record)

    def collect(self, node):
        if isinstance(node, dict):
            if node.get('key') and 'request_sha256' in node and 'raw_content' in node:
                identity = (node['request_sha256'], node['key'])
                previous = self.saved.get(identity)
                if previous is not None and previous['raw_content'] != node['raw_content']:
                    raise ValueError('CONFLICTING_SAVED_ATTEMPT')
                self.saved[identity] = node
            for value in node.values():
                self.collect(value)
        elif isinstance(node, list):
            for value in node:
                self.collect(value)

    def call(self, request, attempt=0, tag=''):
        identity = (sha(request), self.fallback.key(request, attempt))
        if identity in self.saved:
            step = self.saved[identity]
            self.calls['exact_saved_reply'] += 1
            return dict(step, content=step['raw_content'], cached=True)
        reply = self.fallback.call(request, attempt=attempt, tag=tag)
        self.calls.update(self.fallback.counts)
        self.fallback.counts.clear()
        if reply.get('content') is None:
            self.missing.append(dict(tag=tag, attempt=attempt, request_sha256=identity[0], key=identity[1],
                                     transport=reply.get('transport')))
        return reply


def count_status(node, counts):
    if isinstance(node, dict):
        if node.get('schema_validation'):
            counts['schema:' + node['schema_validation']['status']] += 1
        if node.get('verification_status'):
            counts['verify:' + node['verification_status']] += 1
        for value in node.values():
            count_status(value, counts)
    elif isinstance(node, list):
        for value in node:
            count_status(value, counts)


def metrics(rows):
    c = Counter()
    for row in rows:
        if row['gold'] not in (0, 1):
            c['excluded_unknown_gold'] += 1
            continue
        outcome = ('tp' if row['binary'] else 'fn') if row['gold'] == 1 else ('fp' if row['binary'] else 'tn')
        c[outcome] += 1
    tp, fp, fn, tn = (c[k] for k in ('tp', 'fp', 'fn', 'tn'))
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, excluded_unknown_gold=c['excluded_unknown_gold'],
                f1=2 * tp / (2 * tp + fp + fn) if tp else 0)


def source_path(name, rep, arm):
    candidates = [ROOT / f'outputs/universal_repair_v2/runs_offline/{name}/rep{rep}_{arm}_offline.jsonl',
                  ROOT / f'outputs/universal_repair/runs/{name}/rep{rep}_{arm}_live.jsonl']
    return next((path for path in candidates if path.exists()), None)


if args.output.exists():
    raise FileExistsError(args.output)
reports = []
for name, rep in RUNS:
    if (args.sets and name not in args.sets) or (args.reps and rep not in args.reps):
        continue
    for arm in args.arms:
        path = source_path(name, rep, arm)
        if path is None:
            reports.append(dict(set=name, rep=rep, arm=arm, status='NOT_AVAILABLE'))
            continue
        # The historical path is a Git symlink, checked out as plain text on
        # this Windows machine. Read its explicitly declared target artifact.
        canonical = ROOT / 'outputs/guardian_v6/holdout2'
        if name == 'hold_holdout2':
            data = [json.loads(line) for line in (canonical / 'inputs.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
        else:
            data = inputs(name)
        identifiers = [row['id'] for row in data]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError('DUPLICATE_INPUT_IDS')
        saved, coverage = load(path, identifiers)
        gold = json.loads((canonical / 'GOLD_frozen.json').read_text(encoding='utf-8')) if name == 'hold_holdout2' else gold_for(name)
        if set(gold) - set(identifiers):
            raise ValueError('GOLD_HAS_UNEXPECTED_IDS')
        unlabeled_ids = sorted(set(identifiers) - set(gold))
        rows, calls, statuses = [], Counter(), Counter()
        for row in data:
            client = CaseClient(saved[row['id']])
            record = run_v5(row, client, flags=ARMS[arm], attempt=rep - 1)
            binary, accusation = decide(record)
            source_binary, source_accusation = decide(saved[row['id']])
            count_status(record, statuses)
            calls.update(client.calls)
            rows.append(dict(id=row['id'], gold=gold.get(row['id'], {}).get('label'), binary=binary, accusation=accusation,
                             source_binary=source_binary, source_accusation=source_accusation,
                             missing=client.missing,
                             pool=[dict(component=x['component'], target_id=x['candidate']['target_id'],
                                        verification_status=x.get('verification_status')) for x in record.get('pool', [])]))
        report = dict(set=name, rep=rep, arm=arm, status='REPLAYED', source=str(path.relative_to(ROOT)),
                      input_sha256=sha(data), gold_sha256=sha(gold),
                      source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), expected_ids=identifiers,
                      coverage=coverage, excluded_no_gold_ids=unlabeled_ids,
                      rows=rows, metrics=metrics(rows), calls=dict(calls), statuses=dict(statuses))
        reports.append(report)
        # Durable per-phase receipt: a later interruption never discards finished work.
        progress = args.output.with_suffix('.progress.jsonl')
        progress.parent.mkdir(parents=True, exist_ok=True)
        with progress.open('a', encoding='utf-8', newline='\n') as handle:
            handle.write(json.dumps(report, ensure_ascii=False) + '\n')
            handle.flush()
        print(name, rep, arm, report['metrics'], dict(calls), flush=True)
args.output.parent.mkdir(parents=True, exist_ok=True)
if runtime_fingerprints() != runtime_before:
    raise RuntimeError('RUNTIME_CHANGED_DURING_REPLAY')
with args.output.open('x', encoding='utf-8', newline='\n') as handle:
    json.dump(dict(runtime_root=str(ROOT), runtime_head=runtime_head, runtime_fingerprints=runtime_before,
                   script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   network_calls=0, phases=reports), handle, ensure_ascii=False, indent=2)
    handle.write('\n')

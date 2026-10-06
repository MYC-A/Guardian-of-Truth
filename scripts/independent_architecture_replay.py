"""Read-only V4 raw-reply replay and bounded format diagnostic; no model calls.

Run with PYTHONUTF8=1 (legacy runner inputs use locale-dependent read_text).
Only writes a NEW audit report specified by --output; refuses existing files.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import socket
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]


def no_network(*args, **kwargs):
    raise RuntimeError('AUDIT_NETWORK_FORBIDDEN')


socket.create_connection = no_network
socket.socket.connect = no_network
urllib.request.urlopen = no_network

from guardian_truth.integrated.transport import sha
from guardian_truth.source_search.store import SourceStore
from guardian_truth.verification.v4 import decide_v4, run_v4
from guardian_truth.verification.common import quote_q2
from guardian_truth.verification.proof import leaf_quote_ok
from experiments.verification_v2.run import inputs


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def read_records(path):
    lines = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]
    latest = {r['id']: r for r in lines}
    assert not any('error' in r for r in latest.values()), path
    return latest, len(lines)


class StoredReplyClient:
    """Accept only the exact hash of a persisted request; never send a request."""
    def __init__(self, record):
        self.steps = {}
        self.calls = Counter()
        self.collect(record)

    def collect(self, x):
        if isinstance(x, dict):
            if 'request_sha256' in x and 'raw_content' in x:
                old = self.steps.get(x['request_sha256'])
                if old is not None and old['raw_content'] != x['raw_content']:
                    raise AssertionError('CONFLICTING_STORED_REPLIES_FOR_REQUEST_HASH')
                self.steps[x['request_sha256']] = x
            for v in x.values():
                self.collect(v)
        elif isinstance(x, list):
            for v in x:
                self.collect(v)

    def call(self, request, attempt=0, tag=''):
        key = sha(request)
        if key not in self.steps:
            raise AssertionError(f'UNSTORED_REQUEST:{tag}:{key}')
        step = self.steps[key]
        self.calls[tag] += 1
        return dict(step, content=step['raw_content'], cached=True)


def metrics(pred, gold):
    assert set(pred) == set(gold)
    assert all(g['label'] in (0, 1) for g in gold.values())
    tp = sum(bool(p) and gold[i]['label'] == 1 for i, p in pred.items())
    fp = sum(bool(p) and gold[i]['label'] == 0 for i, p in pred.items())
    fn = sum(not p and gold[i]['label'] == 1 for i, p in pred.items())
    tn = len(pred) - tp - fp - fn
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, f1=2 * tp / (2 * tp + fp + fn) if tp else 0.0)


def gold_for(name):
    if name == 'valid46':
        import pandas as pd
        return {r.id: dict(label=int(r.label)) for r in pd.read_parquet(ROOT / 'valid.parquet').itertuples()}
    dirs = {'lb_long': 'lockbox', 'lb2_long': 'lockbox2', 'lb3_long': 'lockbox3'}
    if name in dirs:
        return read_json(ROOT / 'outputs/verification_v2' / dirs[name] / 'long/GOLD_eval_only.json')
    return read_json(ROOT / 'outputs/verification_v4/external' / name[4:] / 'GOLD_eval_only.json')


def format_facts(row):
    """Bounded oracle relation diagnostic, NOT a general NL policy compiler.

    Policy phrase recognition is explicitly limited to clauses in this external
    renderer. Detection uses production event inventory, without IDs/tool names.
    """
    store = SourceStore(dict(prompt=row['prompt'], response=row['response']))
    policy = row['prompt'].split('</policy>', 1)[0].split('<policy>', 1)[-1]
    one_call = re.search(r'You should (?:only|at most) make one tool call at a time', policy)
    no_mixed = re.search(r'if you (?:make|take) a tool call, you should not respond to the user (?:simultaneously|at the same time)', policy)
    calls = [e for e in store.target_events if e.kind == 'call']
    prose = [e for e in store.target_events if e.kind == 'text' and e.text.strip()]
    return dict(F1=bool(one_call and len(calls) >= 2), F2=bool(no_mixed and calls and prose), calls=len(calls))


def replay(name, rep, tag):
    path = ROOT / 'outputs/verification_v2/runs' / name / f'rep{rep}{tag}.jsonl'
    records, nlines = read_records(path)
    rows = {r['id']: r for r in inputs(name)}
    assert set(records) == set(rows), (name, rep, 'incomplete run')
    g = gold_for(name)
    assert set(g) == set(rows)
    count, different = Counter(), []
    for i, record in records.items():
        client = StoredReplyClient(record)
        current = run_v4(rows[i], client, attempt=rep - 1)
        if decide_v4(current) != decide_v4(record):
            different.append(i)
        count.update(client.calls)
    assert not different, (name, rep, different)
    arms = list(decide_v4(next(iter(records.values()))))
    binary = {a: metrics({i: decide_v4(r)[a][0] for i, r in records.items()}, g) for a in arms}
    return dict(set=name, rep=rep, tag=tag, rows=len(rows), stored_lines=nlines,
                exact_request_replays=dict(count), decision_and_accusation_differences=different,
                arms=binary, input_records_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def external_diagnostic():
    rows = {r['id']: r for r in inputs('ext_tau2')}
    facts = {i: format_facts(r) for i, r in rows.items()}
    gold = gold_for('ext_tau2v2')
    positive = {i for i, f in facts.items() if f['F1'] or f['F2']}
    assert all(gold[i]['label'] == 1 for i in positive)
    out = dict(rows=len(gold), F1_rows=sum(f['F1'] for f in facts.values()),
               F2_rows=sum(f['F2'] for f in facts.values()), format_union=len(positive),
               warning='Exploratory on post-hoc gold-v2; phrase recognition is bounded, not an automatic policy compiler.', reps={})
    for rep in (1, 2, 3):
        recs, _ = read_records(ROOT / f'outputs/verification_v2/runs/ext_tau2/rep{rep}_v4.jsonl')
        baseline = {i: decide_v4(recs[i])['A'][0] for i in gold}
        v4 = {i: decide_v4(recs[i])['V4'][0] for i in gold}
        union = {i: int(baseline[i] or i in positive) for i in gold}
        out['reps'][rep] = dict(A=metrics(baseline, gold), V4=metrics(v4, gold),
                               A_plus_oracle_format=metrics(union, gold),
                               corrected_fn=sorted(i for i in gold if union[i] and not baseline[i]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists():
        ap.error('output exists; historical reports are immutable')
    source = 'You must not process the order after receiving explicit confirmation from the user.'
    altered = 'You must process the order after receiving explicit confirmation from the user.'
    report = dict(scope='Raw reply/request-hash replay, not fresh inference or exact-key provider-cache authentication',
                  model_http_calls=0, runtime_replay=[],
                  external_format_diagnostic=external_diagnostic(),
                  q2_polarity_probe=dict(source=source, altered=altered,
                     accepted=quote_q2(altered, [source]), leaf_accepted=leaf_quote_ok(altered, source)))
    for name, rep, tag in [('valid46', 1, '_v4dev3'), ('lb_long', 1, '_v4dev3'),
                           ('lb2_long', 1, '_v4dev3'), ('lb3_long', 1, '_v4dev3'), ('lb3_long', 2, '_v4dev3'),
                           ('ext_tau2', 1, '_v4'), ('ext_tau2', 2, '_v4'), ('ext_tau2', 3, '_v4')]:
        result = replay(name, rep, tag)
        report['runtime_replay'].append(result)
        print(name, rep, result['rows'], 'exact requests', sum(result['exact_request_replays'].values()), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('PASS', sum(r['rows'] for r in report['runtime_replay']), 'rows; no network')


if __name__ == '__main__':
    main()

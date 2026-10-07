"""Offline re-admission of OLD v2 F proposals, current F/P/S, SAME saved R_fix.

This is not v3 inference replay: old requests deliberately lack new context.
Historical inputs, predictions, gold and caches are read-only. Network blocked.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from guardian_truth.integrated.transport import PROVIDERS, sha
from guardian_truth.parsing import decode_json
from guardian_truth.verification.pipeline import packet_for
from guardian_truth.v6fix import provenance as P, structural as S, turnrules as F
from guardian_truth.v6fix.pipeline import Layers, policy_key

BASE = '9794f50df43e919147ee272b6eea5ada7094084a'
MODEL = 'ministral-14b-2512'
RUNS = ROOT / 'outputs/guardian_v6_fix/runs'
CACHE = ROOT / 'outputs/guardian_v6_fix/cache/frules'
PATHS = {
    'lb_long': ('outputs/verification_v2/lockbox/long/inputs.jsonl', 'outputs/verification_v2/lockbox/long/GOLD_eval_only.json'),
    'lb2_long': ('outputs/verification_v2/lockbox2/long/inputs.jsonl', 'outputs/verification_v2/lockbox2/long/GOLD_eval_only.json'),
    'lb3_long': ('outputs/verification_v2/lockbox3/long/inputs.jsonl', 'outputs/verification_v2/lockbox3/long/GOLD_eval_only.json'),
    'ext_tau2': ('outputs/verification_v4/external/tau2/inputs.jsonl', 'outputs/verification_v4/external/tau2v2/GOLD_eval_only.json'),
    'hold_tau2h': ('outputs/universal_repair/holdout/tau2h/inputs.jsonl', 'outputs/universal_repair/holdout/tau2h/GOLD_frozen.json'),
    # Direct resolved Git paths work on Windows without emulated symlinks.
    'hold_holdout2': ('outputs/guardian_v6/holdout2/inputs.jsonl', 'outputs/guardian_v6/holdout2/GOLD_frozen.json'),
    'hold_frozen120': ('outputs/guardian_v6_fix/frozen120/inputs.jsonl', 'outputs/guardian_v6_fix/frozen120/GOLD_frozen.json'),
}
RUNTIME = ['src/guardian_truth/v6fix/' + p + '.py' for p in ('turnrules', 'provenance', 'structural', 'pipeline', 'common')]


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def jsonl(path):
    rows = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.strip():
            row, valid = decode_json(line)
            if not valid or not isinstance(row, dict):
                raise ValueError('INVALID_JSONL: ' + str(path))
            rows.append(row)
    return rows


def index(rows):
    out = {r['id']: r for r in rows}
    if len(out) != len(rows):
        raise ValueError('DUPLICATE_IDS')
    return out


def load_inputs(name):
    if name == 'valid46':
        import pandas as pd
        p = ROOT / 'valid.parquet'
        frame = pd.read_parquet(p)
        rows = [dict(id=r.id, prompt=r.prompt, response=r.response) for r in frame.itertuples()]
        gold = {r.id: dict(label=int(r.label)) for r in frame.itertuples()}
        return index(rows), gold, {str(p.relative_to(ROOT)): fingerprint(p)}
    a, b = (ROOT / p for p in PATHS[name])
    return index(jsonl(a)), json.loads(b.read_text(encoding='utf-8')), {
        str(p.relative_to(ROOT)): fingerprint(p) for p in (a, b)}


class FrozenClient:
    def __init__(self):
        self.keys, self.failures = {}, []

    def call(self, request, attempt=0, tag=''):
        endpoint = PROVIDERS['mistral'][0]
        key = sha(dict(provider='mistral', endpoint=endpoint, model=MODEL, request=request, attempt=attempt))
        path = CACHE / key[:2] / (key + '.json')
        if not path.exists():
            raise ValueError('MISSING_LEGACY_CACHE:' + key)
        rec = json.loads(path.read_text(encoding='utf-8'))
        if rec.get('request_sha256') != sha(request) or rec.get('key') != key or rec.get('attempt') != attempt:
            raise ValueError('LEGACY_CACHE_IDENTITY_MISMATCH:' + key)
        if rec.get('content') is None or rec.get('transport', {}).get('status') != 200:
            raise ValueError('LEGACY_CACHE_UNSUCCESSFUL:' + key)
        self.keys[key] = dict(request_sha256=sha(request), attempt=attempt, file_sha256=fingerprint(path))
        return dict(rec, cached=True)


def legacy_module():
    path = 'src/guardian_truth/v6fix/turnrules.py'
    raw = subprocess.check_output(['git', 'show', BASE + ':' + path], cwd=ROOT)
    module = types.ModuleType('guardian_truth.v6fix._frozen_v2_turnrules')
    module.__package__ = 'guardian_truth.v6fix'
    exec(compile(raw.decode('utf-8'), BASE + ':' + path, 'exec'), module.__dict__)
    return module, hashlib.sha256(raw).hexdigest()


def projected_rules(rules):
    keys = ('type', 'n', 'status', 'source_id', 'quote', 'checks')
    return [{k: r.get(k) for k in keys} for r in rules]


def compact(finding):
    norm = finding.get('norm') or {}
    return dict(layer=finding['layer'], kind=finding['kind'], target_id=finding['target_id'], status=finding['status'],
                fact=finding['fact'], norm_basis=norm.get('basis'),
                unresolved=norm.get('gaps') or (norm.get('checks') or {}).get('conditions'),
                applicability_status=norm.get('applicability_status'))


def metrics(counter):
    tp, fp, fn, tn = (counter[k] for k in ('TP', 'FP', 'FN', 'TN'))
    denom = 2 * tp + fp + fn
    return dict(TP=tp, FP=fp, FN=fn, TN=tn, F1=2 * tp / denom if denom else None,
                precision=tp / (tp + fp) if tp + fp else None, recall=tp / (tp + fn) if tp + fn else None)


def outcome(binary, label):
    return ('TP' if binary else 'FN') if label else ('FP' if binary else 'TN')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, default=ROOT / 'docs/contract_fix_20261007/v6_readmission.json')
    args = ap.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    def blocked(*a, **k):
        raise RuntimeError('NETWORK_DISABLED_FOR_OFFLINE_READMISSION')
    socket.socket = blocked
    socket.create_connection = blocked
    old, old_source_sha = legacy_module()
    client = FrozenClient()
    runtime_before = {p: fingerprint(ROOT / p) for p in RUNTIME}
    report = dict(kind='OLD_PROPOSAL_READMISSION_NOT_V3_INFERENCE', baseline_sha=BASE, legacy_f_source_sha256=old_source_sha,
                  protocol=dict(old_wire='turn_rules_v2', new_wire=F.PROTOCOL_VERSION,
                                base='EXACT_SAVED_R_FIX_BINARY_UNCHANGED',
                                closure_arms={'open': 'tool and provenance universes unresolved (default)',
                                              'closed': 'caller explicitly assumes both tool and provenance universes closed (sensitivity only)'},
                                interpretation='No model calls; no new F extraction responses; no oracle relations; gold only used after predictions.',
                                limitations=['All sets are historical development/diagnostic data.',
                                             'Old proposals omitted full-context v3 input and cannot estimate automatic v3 extraction quality.',
                                             'Closed arm is an explicit assumption, not inferred from a parsed complete catalog.',
                                             'Only frozen binary gold is scored; cause truth requires separate source adjudication.',
                                             'Repetition projections reuse saved base decisions; they are not fresh independent layer runs.']),
                  runtime_sha256=runtime_before, artifacts={}, sets={}, changes=[])
    extraction_cache = {}
    global_counts = defaultdict(Counter)
    projected_views = 0
    for path in sorted(RUNS.glob('*.jsonl')):
        name = path.stem
        inputs, gold, fingerprints = load_inputs(name)
        saved_rows = jsonl(path)
        saved = index(saved_rows)
        if set(saved) != set(gold) or not set(saved) <= set(inputs):
            raise ValueError('INPUT_GOLD_ID_SET_MISMATCH:' + name)
        if any(r['label'] != gold[i]['label'] for i, r in saved.items()):
            raise ValueError('GOLD_LABEL_DRIFT:' + name)
        report['artifacts'].update(fingerprints)
        report['artifacts'][str(path.relative_to(ROOT))] = fingerprint(path)
        counters = defaultdict(Counter)
        stage = Counter()
        set_changes = Counter()
        legacy_mismatches = []
        missing = []
        rule_statuses = Counter()
        for identifier, record in saved.items():
            for budget in (20000, 400000):
                packet = packet_for(inputs[identifier], budget)
                if packet is None:
                    missing.append(dict(id=identifier, budget=budget, reason='NO_PACKET'))
                    continue
                for replica, attempts in (('A', (0, 1)), ('B', (2, 3))):
                    view = f'{budget}_{replica}'
                    archived = record['layers'][view]
                    if archived['complete'] != packet['coverage']['complete_input']:
                        raise ValueError('PACKET_COVERAGE_DRIFT:' + name + ':' + identifier + ':' + view)
                    # The legacy request depends only on deduplicated candidate-line TEXTS.
                    texts = sorted({line['text'] for line in old.candidate_lines(packet['normative_sources'])})
                    identity = json.dumps([texts, attempts], ensure_ascii=False)
                    if identity not in extraction_cache:
                        try:
                            extraction_cache[identity] = old.extract(client, MODEL, packet['normative_sources'], attempts)
                        except ValueError as exc:
                            extraction_cache[identity] = dict(technical=str(exc))
                    extraction = extraction_cache[identity]
                    if 'technical' in extraction:
                        missing.append(dict(id=identifier, view=view, reason=extraction['technical']))
                        continue
                    old_bound = projected_rules(old.bind(extraction, packet['normative_sources']))
                    if old_bound != archived['rules']:
                        legacy_mismatches.append(dict(id=identifier, view=view, saved=archived['rules'], rebuilt=old_bound))
                    rules = F.bind(extraction, packet['normative_sources'])
                    for rule in rules:
                        rule_statuses[view + '|' + rule['status']] += 1
                    old_mechanical = [f for f in archived['findings'] if f['status'] == 'MECHANICAL']
                    for closure in (False, True):
                        arm = 'closed' if closure else 'open'
                        packet['coverage'].update(tool_universe_closed=closure, provenance_universe_closed=closure)
                        # Execute the actual pipeline, including policy-unread gates.
                        # Seed ONLY its extraction proposal cache; do not send a v3 request.
                        layer = Layers(client, MODEL, budget=budget, tool_universe_closed=closure,
                                       provenance_universe_closed=closure)
                        layer.packet = lambda _row, prepared=packet: prepared
                        layer.cache[policy_key(packet['normative_sources'])] = extraction
                        findings = layer.findings(inputs[identifier])['findings']
                        for f in findings:
                            stage[view + '|' + arm + '|' + f['layer'] + '|' + f['status']] += 1
                        mechanical = [f for f in findings if f['status'] == 'MECHANICAL']
                        for rep, base in record['rfix'].items():
                            projected_views += 1
                            before = int(bool(base or old_mechanical))
                            after = int(bool(base or mechanical))
                            label = record['label']
                            if label == 'UNKNOWN':
                                continue
                            for tag, prediction in (('R_fix', base), ('legacy', before), (arm, after)):
                                key = view + '|rep' + rep + '|' + tag
                                # Base/legacy are arm-independent and counted once.
                                if closure and tag in ('R_fix', 'legacy'):
                                    continue
                                counters[key][outcome(prediction, label)] += 1
                                global_counts[key][outcome(prediction, label)] += 1
                            if before != after:
                                category = ('TP_recovered' if after else 'TP_lost') if label else ('FP_added' if after else 'FP_removed')
                                set_changes[view + '|' + arm + '|' + category] += 1
                                report['changes'].append(dict(set=name, id=identifier, view=view, closure=arm, rep=rep,
                                                              label=label, base=base, before=before, after=after, change=category,
                                                              old_mechanical=old_mechanical, new_findings=[compact(f) for f in findings]))
        report['sets'][name] = dict(rows=len(saved), scored_rows=sum(r['label'] != 'UNKNOWN' for r in saved.values()),
                                   base_repetitions=sorted({k for r in saved.values() for k in r['rfix']}),
                                   metrics={k: metrics(v) for k, v in sorted(counters.items())},
                                   transitions=dict(sorted(set_changes.items())), rule_statuses=dict(sorted(rule_statuses.items())),
                                   finding_statuses=dict(sorted(stage.items())), missing=missing, legacy_projection_mismatches=legacy_mismatches)
        print(name, len(saved), 'changes', dict(set_changes), 'missing', len(missing), 'legacy_mismatch', len(legacy_mismatches), flush=True)
    runtime_after = {p: fingerprint(ROOT / p) for p in RUNTIME}
    if runtime_after != runtime_before:
        raise RuntimeError('RUNTIME_CHANGED_DURING_READMISSION')
    report.update(global_metrics={k: metrics(v) for k, v in sorted(global_counts.items())},
                  unique_legacy_requests=len(client.keys), legacy_cache_identity=client.keys, projected_views=projected_views,
                  missing_total=sum(len(s['missing']) for s in report['sets'].values()),
                  legacy_projection_mismatch_total=sum(len(s['legacy_projection_mismatches']) for s in report['sets'].values()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)
        handle.write('\n')
    print('wrote', args.output, 'requests', len(client.keys), 'projected_views', projected_views, flush=True)


if __name__ == '__main__':
    main()

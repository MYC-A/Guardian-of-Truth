"""Full paired offline B2 replay: only the capability-safe lazy-F gate changes.

Runtime inputs drop labels; labels are used only after both complete predictions.
Every model call must match a frozen request/model/attempt/tag exactly.
"""
from collections import Counter
import argparse
import copy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import zipfile

from guardian_truth.integrated.transport import sha
from guardian_truth.submission.cli import MODEL, predict_one, read_rows, row_fingerprint, scheduled_rows
from guardian_truth.v6fix.pipeline import Layers
from guardian_truth.v6fix.turnrules import PROTOCOL_VERSION


def run(bundle, input_path, output):
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read('export_manifest.json'))
        names = archive.namelist()
        if len(names) != len(set(names)) or set(manifest) != set(names) - {'export_manifest.json'}:
            raise ValueError('EXPORT_MANIFEST_MEMBER_SET_MISMATCH')
        for name, expected in manifest.items():
            raw = archive.read(name)
            if len(raw) != expected['bytes'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
                raise ValueError('EXPORT_MEMBER_HASH_MISMATCH')
        prefix = 'legacy/rep1/receipts/'
        frozen = json.loads(archive.read(prefix + 'calls.json'))
        traces = [json.loads(s) for s in archive.read(prefix + 'traces.jsonl').decode('utf-8').splitlines() if s.strip()]
        reference_run = json.loads(archive.read(prefix + 'run.json'))
    rows = read_rows(input_path)
    input_hash = hashlib.sha256(Path(input_path).read_bytes()).hexdigest()
    if reference_run['input_sha256'] != input_hash:
        raise ValueError('INPUT_SHA_MISMATCH')
    index = {r['id']: r for r in traces}
    if len(index) != len(traces) or set(index) != {r['id'] for r in rows}:
        raise ValueError('INCOMPLETE_FROZEN_TRACE_IDS')
    for row in rows:
        if index[row['id']]['input_row_sha256'] != row_fingerprint(row):
            raise ValueError('ROW_FINGERPRINT_MISMATCH')
    records = {r['key']: r for r in frozen}
    if len(records) != len(frozen):
        raise ValueError('DUPLICATE_FROZEN_CALL_KEY')

    class Client:
        model = MODEL
        def __init__(self):
            self.used, self.missing, self.invalid = set(), [], []
        def call(self, request, attempt=0, tag=''):
            key = sha(dict(model=MODEL, request=request, attempt=attempt))
            if key not in records:
                self.missing.append(dict(tag=tag, attempt=attempt, key=key))
                raise ValueError('EXACT_REQUEST_NOT_IN_FROZEN_RECEIPTS')
            receipt = records[key]
            if (receipt['request_sha256'] != sha(request) or receipt['model'] != MODEL
                    or receipt['attempt'] != attempt or receipt['tag'] != tag):
                self.invalid.append(dict(tag=tag, attempt=attempt, key=key))
                raise ValueError('FROZEN_CALL_METADATA_MISMATCH')
            self.used.add(key)
            return copy.deepcopy(receipt)

    arms = {}
    with ExitStack() as stack:
        for name in ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.create_connection'):
            stack.enter_context(patch(name, side_effect=AssertionError('OFFLINE_REPLAY_NETWORK_FORBIDDEN')))
        for arm, lazy, order in [('baseline', False, 'input'), ('lazy_f', True, 'input'),
                                 ('lazy_f_longest', True, 'longest-first')]:
            client = Client()
            layers = Layers(client, MODEL, budget=20000, attempts=(0, 1), frules_max_tokens=700,
                            tolerate_component_errors=True, skip_inapplicable_f=lazy)
            results = {r['id']: predict_one(r, client, layers, 'legacy') for r in scheduled_rows(rows, order)}
            if client.missing:
                raise ValueError('MISSING_EXACT_REQUESTS:' + json.dumps(client.missing))
            if client.invalid:
                raise ValueError('INVALID_FROZEN_CALLS:' + json.dumps(client.invalid))
            changes = []
            for row in rows:
                old, new = index[row['id']], results[row['id']]
                fields = ('binary', 'owner', 'accusation')
                if any(old.get(k) != new.get(k) for k in fields):
                    changes.append(dict(id=row['id'], before={k: old.get(k) for k in fields},
                                        after={k: new.get(k) for k in fields}))
            used = [records[key] for key in client.used]
            removed = [record for key, record in records.items() if key not in client.used]
            if arm == 'baseline' and removed:
                raise ValueError('BASELINE_DID_NOT_CONSUME_FULL_FROZEN_CALL_SET')
            if any(r['tag'] != PROTOCOL_VERSION for r in removed):
                raise ValueError('NON_F_CALL_REMOVED')
            arms[arm] = dict(rows=len(results), changes=changes, missing_requests=client.missing,
                unique_exact_requests=len(used), used_tags=dict(Counter(r['tag'] for r in used)),
                removed_calls=len(removed), removed_tags=dict(Counter(r['tag'] for r in removed)),
                removed_input_tokens=sum((r.get('usage') or {}).get('prompt_tokens', 0) for r in removed),
                removed_output_tokens=sum((r.get('usage') or {}).get('completion_tokens', 0) for r in removed),
                skipped_rows=sum((r.get('layer_trace', {}).get('f_eligibility') or {}).get('status') ==
                                 'SKIPPED_NO_CURRENT_ASSISTANT_CALL' for r in results.values()),
                predictions=[dict(id=row['id'], label=results[row['id']]['binary']) for row in rows])
    import pandas as pd
    labels = pd.read_parquet(input_path).set_index('id')['label']
    for arm in arms.values():
        counts = Counter()
        for prediction in arm['predictions']:
            value = prediction['label']
            if type(value) is not int or value not in (0, 1):
                raise ValueError('NON_BINARY_REPLAY_RESULT')
            counts[('TN', 'FP', 'FN', 'TP')[2 * int(labels[prediction['id']]) + value]] += 1
        arm['metrics'] = {k: counts[k] for k in ('TP', 'FP', 'FN', 'TN')}
        arm['metrics']['F1'] = 2 * counts['TP'] / (2 * counts['TP'] + counts['FP'] + counts['FN'])
    report = dict(scope='Fixed raw replay, not new inference or measured GPU speedup',
                  model=MODEL, input_sha256=input_hash, actual_http_calls=0, arms=arms)
    with Path(output).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    if any(arm['changes'] for arm in arms.values()):
        raise ValueError('REPLAY_DECISION_OR_CAUSE_REGRESSION')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle', 'input', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = run(args.bundle, args.input, args.output)
    print(json.dumps({k: {f: v[f] for f in ('rows', 'unique_exact_requests', 'removed_calls',
        'removed_input_tokens', 'removed_output_tokens', 'skipped_rows', 'metrics', 'changes')}
        for k, v in result['arms'].items()}, ensure_ascii=False))

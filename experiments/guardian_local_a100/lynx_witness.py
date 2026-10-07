"""Versioned Lynx witness repair. Native task/codec unchanged; old outputs preserved.

Full original prompt is preferred if the actual native tokenizer allows it.
Otherwise retrieval selects exact addressed windows and reports every omitted
range. Accusation documents include the observed CURRENT RESPONSE; turn checks
never include their answer in the document. This module does not enforce policy.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading

from guardian_truth.file_lock import process_lock
from guardian_truth.integrated.transport import sha
from guardian_truth.parsing import parse_events
from experiments.guardian_local_a100 import lynx_native_v2 as native
from experiments.guardian_local_a100.lynx_ground import evidence_document
from experiments.guardian_local_a100.run_local import ROOT, OUTROOT, client_for, rows
from experiments.guardian_local_a100.score_local import classify_row
from experiments.research_records import freeze_phase

VERSION = 'lynx-addressed-witness-v4'
QUESTION = 'Is the claim supported by the document?'


def fingerprint(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def current_document(row):
    """Observation of an output/attempt, not proof of its claims or execution."""
    events = parse_events(row['response'], 'response')
    inventory = [dict(id=f't{i}', role=e.role, kind=e.kind, tool=e.name,
                      start=e.source.start, end=e.source.end) for i, e in enumerate(events)]
    return ('\n\n[OBSERVED CURRENT ASSISTANT RESPONSE; an attempted call is not a successful receipt; '
            'assertions in this response are not independent evidence of their truth]\n'
            + json.dumps(inventory, ensure_ascii=False) + '\n' + row['response'])


def omitted(length, intervals):
    gaps, end = [], 0
    for start, stop in sorted(intervals):
        if start > end:
            gaps.append(dict(document='prompt', start=end, end=start))
        end = max(end, stop)
    if end < length:
        gaps.append(dict(document='prompt', start=end, end=length))
    return gaps


def units(prompt, size=1800):
    events = parse_events(prompt, 'prompt')
    out = []
    for i, event in enumerate(events):
        for start in range(event.source.start, event.source.end, size):
            stop = min(start + size, event.source.end)
            text = prompt[start:stop]
            out.append(dict(start=start, end=stop, event=i, role=event.role,
                            kind=event.kind, tool=event.name, text=text))
    # Unparsed spans are indexed too; their role remains unknown.
    for gap in omitted(len(prompt), [(e.source.start, e.source.end) for e in events]):
        for start in range(gap['start'], gap['end'], size):
            stop = min(start + size, gap['end'])
            out.append(dict(start=start, end=stop, event=None, role='unknown', kind='raw',
                            tool=None, text=prompt[start:stop]))
    return sorted(out, key=lambda u: (u['start'], u['end']))


def words(text):
    # Retrieval only; these tokens never establish semantic applicability.
    return set(re.findall(r'[\w.-]{3,}', text.casefold()))


def selected_document(row, claim, budget_bytes, accuse):
    prompt = row['prompt']
    pool = units(prompt)
    query = words(row['response'] + '\n' + claim)
    counts = Counter(word for unit in pool for word in words(unit['text']))
    latest_user = max((unit['event'] for unit in pool if unit['role'] == 'user' and unit['event'] is not None), default=None)
    def score(unit):
        overlap = query & words(unit['text'])
        value = sum(math.log1p(len(pool) / counts[word]) for word in sorted(overlap))
        if unit['role'] == 'user' and unit['event'] == latest_user:
            value += 1000
        return value
    ranked = sorted(range(len(pool)), key=lambda i: (-score(pool[i]), pool[i]['start']))
    # Read neighboring original windows too; this protects local guards, tuple
    # context and proposal/answer adjacency without assigning them semantics.
    order = list(dict.fromkeys(j for i in ranked for j in (i, i-1, i+1) if 0 <= j < len(pool)))
    chosen, used = [], 0
    for i in order:
        unit = pool[i]
        cost = len(unit['text'].encode('utf-8')) + 180
        if used + cost <= budget_bytes:
            chosen.append(unit)
            used += cost
    chosen.sort(key=lambda u: u['start'])
    spans = [dict(document='prompt', start=u['start'], end=u['end'], role=u['role'], kind=u['kind'], tool=u['tool']) for u in chosen]
    gaps = omitted(len(prompt), [(u['start'], u['end']) for u in chosen])
    parts = ['[EXACT ORIGINAL SOURCE WINDOWS; omitted ranges exist; absence from this view does not prove absence from the original input]']
    for unit in chosen:
        parts.append(f"[prompt:{unit['start']}:{unit['end']} role={unit['role']} kind={unit['kind']} tool={unit['tool']}]\n" + unit['text'])
    if accuse:
        parts.append(current_document(row))
    meta = dict(version=VERSION, mode='SELECTED', complete_input=not gaps,
                original_prompt_sha256=fingerprint(prompt), current_in_document=accuse,
                current_response_sha256=fingerprint(row['response']), selected=spans, unread=gaps,
                budget_bytes=budget_bytes, selection='LEXICAL_RARITY_PLUS_ADJACENT_ORIGINAL_WINDOWS_NOT_SEMANTIC_PROOF')
    return '\n\n'.join(parts), meta


def full_document(row, accuse):
    text = '[COMPLETE ORIGINAL PROMPT]\n' + row['prompt']
    if accuse:
        text += current_document(row)
    return text, dict(version=VERSION, mode='FULL', complete_input=True, unread=[],
                     original_prompt_sha256=fingerprint(row['prompt']),
                     current_response_sha256=fingerprint(row['response']), current_in_document=accuse)


def choose_request(row, answer, accuse, model, token_count, *, max_tokens=600, context_tokens=8000):
    """Try full original, then explicit bounded views; never truncate a request."""
    tried = []
    question = QUESTION if accuse else 'What does the document say?'
    for budget in (None, 48000, 36000, 24000, 16000, 8000):
        document, meta = full_document(row, accuse) if budget is None else selected_document(row, answer, budget, accuse)
        request = dict(model=model, temperature=0, max_tokens=max_tokens,
                       messages=native.messages(document, question, answer))
        n = token_count(request)
        tried.append(dict(mode=meta['mode'], budget_bytes=budget, input_tokens=n))
        if n + max_tokens <= context_tokens:
            return request, dict(meta, input_tokens=n, attempts=tried)
    return None, dict(status='CONTEXT_NOT_FIT', attempts=tried, current_in_document=accuse)


def support_status(check, meta):
    if check.get('status') != 'VALID':
        return 'TECHNICAL_UNJUDGED'
    if not meta.get('complete_input'):
        return 'MODEL_SUPPORTED_WITH_GAPS' if check['verdict'] == 'PASS' else 'UNRESOLVED_WITH_GAPS'
    return 'MODEL_SUPPORTED' if check['verdict'] == 'PASS' else 'MODEL_UNSUPPORTED'


def read_records(path, expected, *, allow_missing=False):
    result = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        key = row['id']
        if key in result or key not in expected:
            raise ValueError('DUPLICATE_OR_FOREIGN_REVIEWER_ID')
        result[key] = row
    if not allow_missing and set(result) != set(expected):
        raise ValueError('INCOMPLETE_REVIEWER_INPUT')
    return result


def checks_of(result):
    checks = [result['turn']] if 'turn' in result else []
    for accusation in result.get('accusations') or []:
        checks.extend(accusation[k] for k in ('old_check', 'action_check', 'witness_check') if k in accusation)
    return checks


def row_status(result):
    checks = checks_of(result)
    return 'EXECUTED' if checks and all(c.get('status') == 'VALID' for c in checks) else 'PARTIAL_TECHNICAL'


def judge(client, request, base):
    result = native.execute(client, request, base, 8000)
    if (result.get('receipt') or {}).get('finish_reason') == 'length':
        result.update(status='TECHNICAL_UNJUDGED', raw_score=result.get('verdict'), verdict=None,
                      rejection='COMPLETION_LENGTH_LIMIT')
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model-id', required=True)
    ap.add_argument('--qwen-root', type=Path, required=True)
    ap.add_argument('--distill-root', type=Path, required=True)
    ap.add_argument('--legacy-runs', type=Path, required=True)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--max-calls', type=int, default=150)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    base = args.output
    base.mkdir(parents=True, exist_ok=True)
    client = client_for('local-llamacpp', args.model_id, base / 'cache', max_calls=args.max_calls, timeout=180)
    def count(request):
        return native.prompt_tokens(client.live.endpoint, request)
    def check(request):
        return judge(client, request, base)
    data = rows('valid46')
    ids = {r['id'] for r in data}
    legacy = {}
    for line in args.legacy_runs.read_text(encoding='utf-8').splitlines():
        record = json.loads(line)
        if record['set'] == 'valid46':
            if record['id'] in legacy:
                raise ValueError('DUPLICATE_LEGACY_ID')
            legacy[record['id']] = record
    if set(legacy) != ids:
        raise ValueError('INCOMPLETE_LEGACY_VALID46')
    qwen = read_records(args.qwen_root / 'valid46/B2_rep1.jsonl', ids)
    distill = {
        'A': read_records(args.distill_root / 'valid46/AM_rep1.jsonl', ids),
        'B2': read_records(args.distill_root / 'valid46/B2_rep1.jsonl', ids, allow_missing=True),
    }
    jobs = []
    for row in data:
        candidates = []
        q = qwen[row['id']]
        if (q.get('accusation') or {}).get('text'):
            candidates.append(dict(model='qwen', arm='B2', text=q['accusation']['text'],
                                   reviewer_class=classify_row(q, 'B2', 'binary')))
        for acc in legacy[row['id']].get('accusations') or []:
            source = distill[acc['arm']].get(row['id'])
            expected_text = ((source or {}).get('accusation_rfix' if acc['arm'] == 'A' else 'accusation') or {}).get('text')
            if expected_text != acc['text']:
                raise ValueError('LEGACY_ACCUSATION_SOURCE_MISMATCH')
            candidates.append(dict(model='distill', arm=acc['arm'], text=acc['text'], old_check=acc['check'],
                                   reviewer_class=classify_row(source, acc['arm'], 'binary_rfix' if acc['arm'] == 'A' else 'binary')))
        jobs.append(dict(row=row, candidates=candidates, legacy_turn=legacy[row['id']]['turn']))
    manifest = dict(version=VERSION, model=args.model_id, max_calls=args.max_calls,
                    max_tokens=600, context_tokens=8000, workers=args.workers,
                    runner_sha256=fingerprint(Path(__file__).read_text(encoding='utf-8')),
                    native_sha256=fingerprint(Path(native.__file__).read_text(encoding='utf-8')),
                    imported_runtime_sha256={name:fingerprint(Path(__file__).with_name(name).read_text(encoding='utf-8'))
                                             for name in ('lynx_ground.py','run_local.py','score_local.py')},
                    task='Factual support; raw FAIL->1 is diagnostic only; no policy enforcement',
                    legacy_blob_sha256=hashlib.sha256(args.legacy_runs.read_bytes()).hexdigest())
    path = base / 'runs.jsonl'
    with process_lock(base / 'run.lock'):
        freeze_phase(path, ROOT, manifest, jobs)
        completed = {}
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                value = json.loads(line)
                if value['id'] in completed or value['id'] not in ids:
                    raise ValueError('DUPLICATE_OR_FOREIGN_RESULT_ID')
                completed[value['id']] = value
        lock = threading.Lock()
        def one(job):
            row = job['row']
            if row['id'] in completed:
                return
            pending = []
            for candidate in job['candidates']:
                item = dict(candidate, candidate_id=sha({k:candidate[k] for k in ('model','arm','text')}))
                for field in ('old_check','action_check','witness_check'):
                    item.setdefault(field, dict(status='UNCHECKED',verdict=None))
                pending.append(item)
            result = dict(id=row['id'], version=VERSION, legacy_turn=job['legacy_turn'], accusations=pending)
            try:
                request, meta = choose_request(row, row['response'], False, args.model_id, count)
                result['turn_meta'] = meta
                result['turn'] = check(request) if request else dict(status='CONTEXT_NOT_FIT', verdict=None)
                for item in result['accusations']:
                    old_doc, old_meta = evidence_document(row, 20000)
                    if old_doc is None:
                        item['old_check'] = dict(status='NO_EVIDENCE_VIEW', verdict=None)
                        item['action_check'] = dict(status='NO_EVIDENCE_VIEW', verdict=None)
                    else:
                        if item['old_check'].get('status') == 'UNCHECKED':
                            item['old_check'] = check(dict(model=args.model_id, temperature=0, max_tokens=600,
                                                         messages=native.messages(old_doc, QUESTION, item['text'])))
                        item['action_check'] = check(dict(model=args.model_id, temperature=0, max_tokens=600,
                                                        messages=native.messages(old_doc + current_document(row), QUESTION, item['text'])))
                    item['old_meta'] = old_meta
                    request, meta = choose_request(row, item['text'], True, args.model_id, count)
                    item['witness_meta'] = meta
                    item['witness_check'] = check(request) if request else dict(status='CONTEXT_NOT_FIT', verdict=None)
                    item['support_status'] = support_status(item['witness_check'], meta)
                    item['policy_proof'] = 'NOT_ESTABLISHED_BY_FACTUAL_JUDGE'
                result['status'] = row_status(result)
            except Exception as error:
                result.update(status='TECHNICAL_UNJUDGED', error=type(error).__name__, detail=str(error)[:300])
            with lock:
                with path.open('a', encoding='utf-8', newline='\n') as f:
                    f.write(json.dumps(result, ensure_ascii=False) + '\n')
                    f.flush()
                    os.fsync(f.fileno())
                completed[row['id']] = result
                print(json.dumps(dict(done=len(completed), expected=46, id=row['id'], status=result['status'])), flush=True)
        with ThreadPoolExecutor(args.workers) as pool:
            list(pool.map(one, jobs))
        if set(completed) != ids:
            raise ValueError('INCOMPLETE_RESULT_IDS')
        summary = dict(version=VERSION, rows=46, transport_counts=client.counts,
                       technical_rows=sum(r['status'] != 'EXECUTED' for r in completed.values()),
                       checks=dict(Counter(c.get('status') for r in completed.values() for c in checks_of(r))),
                       note='Score all expected rows separately; no default or production change.')
        target = base / 'execution_summary.json'
        if not target.exists():
            with target.open('x', encoding='utf-8') as f:
                json.dump(summary, f, indent=2)


if __name__ == '__main__':
    main()

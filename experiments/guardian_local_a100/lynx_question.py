"""Question-only Lynx control; reuse the frozen witness document unchanged."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import threading

from guardian_truth.file_lock import process_lock
from guardian_truth.integrated.transport import sha
from guardian_truth.parsing import parse_events
from experiments.guardian_local_a100 import lynx_native_v2 as native
from experiments.guardian_local_a100.lynx_witness import fingerprint, judge, read_records
from experiments.guardian_local_a100.run_local import ROOT, client_for, rows
from experiments.guardian_local_a100.score_lynx_witness import binary, measure
from experiments.guardian_local_a100.score_local import gold_for
from experiments.research_records import freeze_phase

VERSION = 'lynx-native-question-v5'
OLD_QUESTION = 'What does the document say?'


def question_request(row, original):
    """Replace only the code-owned QUESTION field, verifying the old packet."""
    users = [e for e in parse_events(row['prompt'], 'prompt') if e.role == 'user']
    if not users:
        raise ValueError('NO_PARSED_USER_QUESTION')
    event = users[-1]
    question = row['prompt'][event.source.start:event.source.end]
    if not question.strip():
        raise ValueError('EMPTY_USER_QUESTION')
    request = copy.deepcopy(original)
    content = request['messages'][0]['content']
    # Split by the complete known native prefix, not delimiters inside source.
    prefix = native.PROMPT.split('{question}', 1)[0]
    boundary = '\n\n--\nDOCUMENT:\n'
    old_prefix = prefix + OLD_QUESTION + boundary
    if len(request['messages']) != 1 or request['messages'][0]['role'] != 'user' or not content.startswith(old_prefix):
        raise ValueError('UNEXPECTED_WITNESS_WIRE')
    rest = content[len(old_prefix):]
    answer_suffix = native.PROMPT.split('{answer}', 1)[1].replace('{{', '{').replace('}}', '}')
    if not rest.endswith('\nANSWER:\n' + row['response'] + answer_suffix):
        raise ValueError('WITNESS_ANSWER_CHANGED')
    request['messages'][0]['content'] = prefix + question + boundary + rest
    return request, dict(document='prompt', start=event.source.start, end=event.source.end,
                         question_sha256=fingerprint(question))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--witness', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--model-id', required=True)
    ap.add_argument('--max-calls', type=int, default=60)
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    data = rows('valid46')
    ids = {r['id'] for r in data}
    witness = read_records(a.witness/'runs.jsonl', ids)
    client = client_for('local-llamacpp', a.model_id, a.output/'cache', max_calls=a.max_calls, timeout=180)
    jobs = []
    for row in data:
        prior = witness[row['id']]
        check = prior.get('turn') or {}
        key = check.get('request_sha256')
        request = meta = None
        error = None
        if key:
            original = json.loads((a.witness/'packets'/f'{key}.json').read_text(encoding='utf-8'))
            if sha(original) != key or original['model'] != a.model_id or original['max_tokens'] != 600:
                raise ValueError('WITNESS_PACKET_IDENTITY_CHANGED')
            try:
                request, meta = question_request(row, original)
            except ValueError as exc:
                error = str(exc)
        else:
            error = 'NO_FROZEN_WITNESS_REQUEST'
        jobs.append(dict(id=row['id'], request=request, question_source=meta, error=error,
                         original_request_sha256=key, legacy_turn=prior['legacy_turn'],
                         witness_turn=check, witness_meta=prior.get('turn_meta')))
    config = dict(version=VERSION, model=a.model_id, workers=a.workers, max_calls=a.max_calls,
                  max_tokens=600, context_tokens=8000,
                  runner_sha256=fingerprint(Path(__file__).read_text(encoding='utf-8')),
                  runtime_sha256={n:fingerprint(Path(__file__).with_name(n).read_text(encoding='utf-8'))
                                 for n in ('lynx_native_v2.py','lynx_witness.py','run_local.py',
                                           'score_lynx_witness.py','method_synthesis.py','score_local.py')},
                  control='Only QUESTION changes; same document/answer, no repacking, factual task not policy proof')
    path = a.output/'runs.jsonl'
    with process_lock(a.output/'run.lock'):
        freeze_phase(path, ROOT, config, jobs)
        done = read_records(path, ids, allow_missing=True) if path.exists() else {}
        lock = threading.Lock()
        def one(job):
            if job['id'] in done:
                return
            result = {k:v for k,v in job.items() if k != 'request'}
            try:
                result['turn'] = (judge(client, job['request'], a.output) if job['request'] else
                                  dict(status='NOT_EXECUTED', verdict=None, error=job['error']))
            except Exception as exc:
                result['turn'] = dict(status='TECHNICAL_UNJUDGED', verdict=None, error=type(exc).__name__)
            with lock:
                with path.open('a', encoding='utf-8', newline='\n') as f:
                    f.write(json.dumps(result, ensure_ascii=False)+'\n')
                    f.flush()
                    os.fsync(f.fileno())
                done[job['id']] = result
                print(json.dumps(dict(done=len(done), expected=len(ids), id=job['id'], status=result['turn']['status'])), flush=True)
        with ThreadPoolExecutor(a.workers) as pool:
            list(pool.map(one, jobs))
        result = read_records(path, ids)
        gold = {k:v['label'] for k,v in gold_for('valid46').items()}
        report = dict(version=VERSION, rows=len(ids), diagnostic_projection='FAIL->ERROR; not a policy certificate',
                      arms={name:measure({k:binary(r[field]) for k,r in result.items()},gold)
                            for name,field in [('legacy_v3','legacy_turn'),('witness_v4','witness_turn'),('question_v5','turn')]},
                      question_flips=[dict(id=k,label=gold[k],old=binary(r['witness_turn']),new=binary(r['turn']))
                                      for k,r in result.items() if binary(r['witness_turn'])!=binary(r['turn'])],
                      full_prompt_rows=sum(bool((r.get('witness_meta') or {}).get('complete_input')) for r in result.values()),
                      transport_counts=client.counts,
                      binary_gold_sha256=fingerprint(json.dumps(gold,sort_keys=True)),
                      runs_sha256=fingerprint(path.read_text(encoding='utf-8')))
        score = a.output/'score.json'
        if not score.exists():
            with score.open('x',encoding='utf-8') as f:
                json.dump(report,f,ensure_ascii=False,indent=2)
                f.write('\n')
        print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()

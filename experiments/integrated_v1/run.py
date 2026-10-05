"""Frozen integrated-v1 runner: resumable phase ledger over the public review() API.

  python -m experiments.integrated_v1.run --phase valid46|syn_m1 --provider mistral|ollama --profile baseline|integrated --rep K
  python -m experiments.integrated_v1.run --plan            # print the frozen matrix, no network
Inference sees only prompt/response (inputs carry no labels). One output line per row, appended and
fsync'ed after each row; a restart skips completed rows. Budgets come from FREEZE.json; the transport
ledger keeps the counters across restarts.
"""
import argparse, hashlib, json, os, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from guardian_truth.integrated import ReviewConfig, Transport, review

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/integrated_v1'
FREEZE = ROOT / 'docs/integrated_v1/FREEZE.json'


def inputs(phase):
    if phase == 'valid46':
        import pandas as pd
        d = pd.read_parquet(ROOT / 'valid.parquet')
        return [dict(id=r.id, prompt=r.prompt, response=r.response) for r in d.itertuples()]
    if phase == 'syn_m1':
        return [json.loads(x) for x in (ROOT / 'outputs/multipacket_v1/suite_syn_m1/inputs.jsonl').read_text().splitlines()]
    raise ValueError(phase)


def compact(res):
    keep = ('tag', 'admission', 'decision', 'raw_decision', 'normalization', 'trigger', 'fallback_after', 'usage', 'seconds',
            'cached', 'key', 'request_sha256', 'request_bytes', 'finish_reason', 'response_model', 'transport')
    steps = []
    for s in res['steps']:
        c = {k: s.get(k) for k in keep if k in s}
        a = s.get('admitted')
        if a:
            c.update(reason=a['reason'], regulated_action=a['regulated_action'], norms=a['applicable_norms'],
                     evidence=[e['source_id'] for e in a['supporting_evidence']], open_questions=a['open_questions'])
        steps.append(c)
    return dict(binary=res['binary'], final_decision=res['final_decision'], projection=res['projection'],
                proof_status=res['proof_status'], decision_owner=res['decision_owner'], model_decision=res['model_decision'],
                first_model_decision=res['first_model_decision'], guard_error=res['guard']['established_error'],
                guard_findings=[f['code'] for f in res['guard']['findings']],
                relation_decisive=(res['relations'] or {}).get('decisive'),
                relation_kinds=sorted({f['kind'] + ':' + str(f.get('relation')) for f in (res['relations'] or {}).get('facts', []) if f['decisive']}),
                packet=res['packet'], source_sha256=res['source_sha256'], cost=res['cost'], steps=steps,
                gaps=len(res['gaps']))


def run(phase, provider, profile, rep, workers):
    freeze = json.loads(FREEZE.read_text())
    fam = freeze['families'][provider]
    cfg = ReviewConfig.profile(profile, provider=provider, model=fam['model'], budget_bytes=freeze['budget_bytes'], attempt=rep - 1)
    client = Transport(provider, fam['model'], OUT / 'cache' / provider, max_calls=fam['max_calls'],
                       max_tokens_total=fam['max_tokens_total'], retry_failed=freeze['retry_failed'])
    path = OUT / f'phase_{phase}' / provider / profile / f'rep{rep}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(x)['id'] for x in path.read_text().splitlines()} if path.exists() else set()
    rows = [r for r in inputs(phase) if r['id'] not in done]
    lock = threading.Lock()
    ledger = OUT / 'phase_ledger.jsonl'

    def one(r):
        try:
            res = compact(review(r['prompt'], r['response'], cfg, client=client))
        except Exception as e:  # recorded, never silently dropped
            res = dict(binary=0, final_decision=None, projection='RUNNER_EXCEPTION_PROJECTED_0', error=f'{type(e).__name__}: {e}'[:300])
        with lock:
            with open(path, 'a') as f:
                f.write(json.dumps(dict(id=r['id'], rep=rep, provider=provider, profile=profile, **res), ensure_ascii=False) + '\n')
                f.flush(); os.fsync(f.fileno())
            print(phase, provider, profile, rep, r['id'][:48], res.get('final_decision'), res.get('projection'), flush=True)
    with open(ledger, 'a') as f:
        f.write(json.dumps(dict(event='START', phase=phase, provider=provider, profile=profile, rep=rep, todo=len(rows), done=len(done),
                                freeze_sha256=hashlib.sha256(FREEZE.read_bytes()).hexdigest())) + '\n')
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, rows))
    n = len(path.read_text().splitlines())
    with open(ledger, 'a') as f:
        f.write(json.dumps(dict(event='END', phase=phase, provider=provider, profile=profile, rep=rep, rows=n,
                                transport=client.counts, sent_total=client.sent, tokens_total=client.tokens)) + '\n')
    print('END', phase, provider, profile, rep, n, client.counts)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase'); ap.add_argument('--provider'); ap.add_argument('--profile'); ap.add_argument('--rep', type=int, default=1)
    ap.add_argument('--workers', type=int, default=4); ap.add_argument('--plan', action='store_true')
    a = ap.parse_args()
    if a.plan:
        print(json.dumps(json.loads(FREEZE.read_text())['matrix'], indent=1))
    else:
        run(a.phase, a.provider, a.profile, a.rep, a.workers)

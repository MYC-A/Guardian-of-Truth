"""Verify-the-positives stage over saved run records (cost only on ERROR rows).
python -m experiments.guardian_fast.postverify --set S --variant T0
Adds rec['Av'] = narrow-verifier verdict for the base (review) ERROR claim, and per-row keys:
  binary_lenient: ERROR unless the verifier REFUTED the claim   binary_strict: ERROR only if SUPPORTED
Mechanical guard errors are never re-opened."""
import argparse, json, os, threading, time
from concurrent.futures import ThreadPoolExecutor

from guardian_truth.repair.v5 import ARMS, verify
from guardian_truth.verification.pipeline import packet_for, _a_candidate
from experiments.guardian_local_a100.run_local import rows, client_for, model_dir, ROOT
from experiments.guardian_fast import run_fast as RF   # installs 429 retry
LOCAL = RF.LOCAL


def candidate(rec):
    A = rec['A']
    if A.get('guard_error'):
        return None
    c = _a_candidate(dict(reasons=A.get('reasons') or []))
    if c:
        return c
    adm = rec.get('A_adm2') or {}
    if adm.get('decision') == 'ERROR' and adm.get('target_id'):
        return dict(origin='A', target_id=adm['target_id'], requirement=None, reason=adm.get('reason'),
                    policy_source_ids=[], evidence_source_ids=[])
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--set', required=True); ap.add_argument('--variant', required=True)
    ap.add_argument('--model-id', default='ministral-14b-2512'); ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    src = RF.OUT / model_dir(a.model_id) / 'runs' / a.set / f'{a.variant}.jsonl'
    dst = RF.OUT / model_dir(a.model_id) / 'runs' / a.set / f'{a.variant}+V.jsonl'
    base = LOCAL / 'vllm' / model_dir(a.model_id)
    client = client_for('local-vllm', a.model_id, base / 'cache' / 'review', retry_failed=8)
    rowmap = {r['id']: r for r in rows(a.set)}
    recs = [json.loads(l) for l in open(src)]
    done = set(json.loads(l)['id'] for l in open(dst)) if dst.exists() else set()
    lock = threading.Lock()

    def one(r):
        rec = r['rec']
        if r.get('error'):
            out = r
        else:
            out = dict(r); out['binary_lenient'] = out['binary_strict'] = r['binary']; out['av_status'] = None
            c = candidate(rec) if rec.get('base_error') else None
            if c is not None:
                s = time.time()
                rp = packet_for(rowmap[r['id']], 20000)
                v = verify(client, rp, c, a.model_id, 0, 'verify_A', ARMS['R_fix'])
                out['Av'] = {k: v.get(k) for k in ('verification_status', 'verdict', 'admission', 'analysis', 'usage', 'transport')}
                out['av_status'] = v['verification_status']
                out['av_s'] = round(time.time() - s, 1)
                out['binary_lenient'] = 0 if v['verification_status'] == 'REFUTED' else r['binary']
                out['binary_strict'] = 1 if (v['verification_status'] == 'SUPPORTED' or not r['binary']) and r['binary'] else (0 if r['binary'] and not r['rec'].get('pool') else r['binary'])
        with lock:
            with open(dst, 'a') as f:
                f.write(json.dumps(out, ensure_ascii=False, default=str) + '\n')

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, [r for r in recs if r['id'] not in done]))
    print('done', a.set, a.variant, len(recs), dict(client.counts))


if __name__ == '__main__':
    main()

"""Fast Guardian runner: R_fix decision only (the v6fix model layers never changed a decision in 1908 saved rows),
optionally with a compact blind pre-pass. Same sets/rows/gold/model as guardian_local_a100.run_local.
python -m experiments.guardian_fast.run_fast --set valid46 --variant N0 --model-id ministral-14b-2512 --workers 6
Records: outputs/guardian_fast/<model>/runs/<set>/<variant><tag>.jsonl (+ wall seconds per row)."""
import argparse, json, os, threading, time, random
from concurrent.futures import ThreadPoolExecutor

from guardian_truth.file_lock import process_lock
from guardian_truth.integrated import transport as _T
from guardian_truth.repair.v5 import ARMS, run_v5, decide as decide_v5
from experiments.research_records import failed_record, expected_manifest, load_records, freeze_phase, technical_gaps
from experiments.guardian_local_a100.run_local import rows, client_for, model_dir, ROOT
from .hook_fast import Hook3

_orig_post = _T.post


def _post_retry(url, key, payload, timeout=180):
    # API rate limits / transient errors are infrastructure, not model output: back off and retry.
    for k in range(8):
        data, log = _orig_post(url, key, payload, timeout=timeout)
        if data is not None or log.get('status') not in (429, 500, 502, 503, 504, 'EXC'):
            return data, log
        time.sleep(min(30, 2 ** k) * (0.5 + random.random()))
    return data, log


_T.post = _post_retry

OUT = ROOT / 'outputs/guardian_fast'
LOCAL = ROOT / 'outputs/guardian_local_a100'
VARIANTS = {
    'N0': dict(pre=None),                                   # R_fix only (no pre-pass, no layers)
    'T0': dict(pre='terse'),                                  # R_fix with a length-capped review (speed)
    'B2': dict(pre='blind2', pre_max_tokens=3400),          # old blind pass, no layers
    'C1': dict(pre='cb1', pre_max_tokens=900),              # compact grounded rules
    'C2': dict(pre='cb2', pre_max_tokens=1300),             # + entities + computed values
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--set', required=True); ap.add_argument('--variant', required=True, choices=sorted(VARIANTS))
    ap.add_argument('--model-id', default='ministral-14b-2512'); ap.add_argument('--backend', default='vllm')
    ap.add_argument('--workers', type=int, default=6); ap.add_argument('--ids')
    ap.add_argument('--max-request-bytes', type=int, default=60000)
    ap.add_argument('--review-max-tokens', type=int, default=None)
    ap.add_argument('--tag', default='')
    a = ap.parse_args()
    v = VARIANTS[a.variant]; provider = f'local-{a.backend}'
    base = LOCAL / a.backend / model_dir(a.model_id)
    client = client_for(provider, a.model_id, base / 'cache' / 'review', retry_failed=8)
    path = OUT / model_dir(a.model_id) / 'runs' / a.set / f'{a.variant}{a.tag}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    selected = [r for r in rows(a.set) if not a.ids or r['id'] in a.ids.split(',')]
    with process_lock(path.with_suffix('.run.lock')):
        freeze_phase(path, ROOT, dict(variant=a.variant, set=a.set, model_id=a.model_id, pre=v['pre'], pre_max_tokens=v.get('pre_max_tokens'),
                                      max_request_bytes=a.max_request_bytes, workers=a.workers, flags=sorted(ARMS['R_fix'])),
                     [{k: r[k] for k in ('id', 'prompt', 'response')} for r in selected])
        expected = expected_manifest(path, [r['id'] for r in selected])
        have, _ = load_records(path, expected, allow_missing=True)
        todo = [r for r in selected if r['id'] not in have or failed_record(have[r['id']])]
        lock = threading.Lock(); t0 = time.time()

        def one(row):
            hook = Hook3(client, v['pre'], a.model_id, original_row=row, max_request_bytes=a.max_request_bytes,
                         max_tokens=v.get('pre_max_tokens', 1700))
            out = dict(id=row['id'], set=a.set, variant=a.variant, model=a.model_id, pre=v['pre'])
            s = time.time()
            try:
                rec = run_v5(row, hook, flags=ARMS['R_fix'], provider=provider, model=a.model_id, attempt=0,
                             review_max_tokens=a.review_max_tokens)
                d, acc = decide_v5(rec)
                out.update(rec=rec, pre_steps=hook.log, binary=d, accusation=acc)
            except Exception as e:
                out.update(error=f'{type(e).__name__}: {e}'[:400], pre_steps=hook.log)
            out['wall_s'] = round(time.time() - s, 1)
            out['technical_gaps'] = technical_gaps(out)
            with lock:
                with open(path, 'a', encoding='utf-8', newline='\n') as f:
                    f.write(json.dumps(out, ensure_ascii=False, default=str) + '\n'); f.flush(); os.fsync(f.fileno())

        with ThreadPoolExecutor(a.workers) as ex:
            list(ex.map(one, todo))
        print(a.set, a.variant, 'rows', len(todo), 'wall', round(time.time() - t0), dict(client.counts), flush=True)


if __name__ == '__main__':
    main()

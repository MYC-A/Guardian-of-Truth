"""THINK-gate runner: four_arms run.py + n>1 samples, kinds in job order, larger batch. Stdlib only.
    python run.py --python <venv> --model <dir> --jobs jobs.json --out out.json [--extra "<vllm flags>"]
"""
import argparse
import json
import os
import shlex
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SERVED = 'guardian-arm'


def post(url, body, timeout=1800):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--python', required=True)
    ap.add_argument('--model', required=True)
    ap.add_argument('--jobs', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--extra', default='')
    ap.add_argument('--port', type=int, default=18126)
    a = ap.parse_args()
    jobs = json.load(open(a.jobs))
    env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1')
    for k in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD'):
        env.pop(k, None)
    cmd = [a.python, '-m', 'vllm.entrypoints.openai.api_server', '--model', a.model, '--tokenizer', a.model,
           '--served-model-name', SERVED, '--host', '127.0.0.1', '--port', str(a.port),
           '--max-model-len', '40960', '--max-num-seqs', '48', '--gpu-memory-utilization', '0.88',
           '--generation-config', 'vllm', '--chat-template-content-format', 'string',
           '--enable-prefix-caching', '--enable-chunked-prefill', '--dtype', 'bfloat16', '--kv-cache-dtype', 'auto',
           '--max-logprobs', '20'] + shlex.split(a.extra)
    log = open(a.out + '.server.log', 'w')
    t0 = time.time()
    proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f'http://127.0.0.1:{a.port}'
    out = dict(jobs=len(jobs), results={}, kind_seconds={})
    try:
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f'server exited rc={proc.returncode}')
            try:
                urllib.request.urlopen(base + '/health', timeout=5)
                break
            except Exception:
                if time.time() - t0 > 1500:
                    raise TimeoutError('startup')
                time.sleep(5)
        out['startup_s'] = round(time.time() - t0, 1)

        def one(j):
            try:
                d = post(base + '/v1/chat/completions', dict(j['body'], model=SERVED))
                return j['id'], dict(samples=[dict(content=c['message'].get('content'), finish=c['finish_reason'])
                                              for c in d['choices']], completion_tokens=d['usage']['completion_tokens'])
            except Exception as e:
                return j['id'], dict(error=f'{type(e).__name__}: {str(e)[:300]}')
        for kind in dict.fromkeys(j['id'].split('|')[0] for j in jobs):
            sub = [j for j in jobs if j['id'].startswith(kind + '|')]
            if not sub:
                continue
            t = time.time()
            with ThreadPoolExecutor(max_workers=16) as ex:
                out['results'].update(dict(ex.map(one, sub)))
            out['kind_seconds'][kind] = round(time.time() - t, 1)
            print(kind, len(sub), out['kind_seconds'][kind], 's', flush=True)
            json.dump(out, open(a.out, 'w'), ensure_ascii=False)
    except Exception as e:
        out['failure'] = f'{type(e).__name__}: {e}'
        print(out['failure'], flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(60)
        except subprocess.TimeoutExpired:
            proc.kill()
    json.dump(out, open(a.out, 'w'), ensure_ascii=False)


if __name__ == '__main__':
    main()

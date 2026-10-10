"""Determinism probe: replay recorded wires twice (different order) on one vLLM server and compare outputs.

    python replay.py --python <venv python> --model <dir> --calls <run>/calls --mode normal|invariant --out <json>
Server flags are those of scripts/qwen_vllm_adapter.py (OwnedVllmServer.command). `invariant` adds
VLLM_BATCH_INVARIANT=1 and --attention-backend FLASH_ATTN. Prefix caching stays on (production setting).
"""
import argparse
import glob
import json
import os
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def post(url, body, timeout=900):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def run_pass(base, wires, order, workers=16):
    def one(i):
        t = time.time()
        try:
            d = post(base + '/v1/chat/completions', wires[i])
            c = d['choices'][0]
            return i, dict(content=c['message']['content'], finish=c['finish_reason'],
                           completion_tokens=d['usage']['completion_tokens'], s=time.time() - t)
        except Exception as e:
            return i, dict(error=f'{type(e).__name__}: {str(e)[:200]}')
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = dict(ex.map(one, order))
    return res, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--python', required=True)
    ap.add_argument('--model', required=True)
    ap.add_argument('--calls', required=True)
    ap.add_argument('--mode', choices=['normal', 'invariant'], required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--port', type=int, default=18123)
    a = ap.parse_args()
    wires, tags = [], []
    for f in sorted(glob.glob(os.path.join(a.calls, '*.json'))):
        r = json.load(open(f))
        if r.get('tag') in ('pre_blind', 'review') and r.get('wire'):
            wires.append(r['wire'])
            tags.append(r['tag'])
    served = wires[0]['model']
    env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1')
    for k in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD'):
        env.pop(k, None)
    cmd = [a.python, '-m', 'vllm.entrypoints.openai.api_server', '--model', a.model, '--tokenizer', a.model,
           '--served-model-name', served, '--host', '127.0.0.1', '--port', str(a.port),
           '--max-model-len', '32768', '--max-num-seqs', '16', '--gpu-memory-utilization', '0.88',
           '--generation-config', 'vllm', '--chat-template-content-format', 'string',
           '--enable-prefix-caching', '--enable-chunked-prefill', '--dtype', 'bfloat16', '--kv-cache-dtype', 'auto']
    if a.mode == 'invariant':
        env['VLLM_BATCH_INVARIANT'] = '1'
        cmd += ['--attention-backend', 'FLASH_ATTN']
    log = open(a.out + '.server.log', 'w')
    t0 = time.time()
    proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f'http://127.0.0.1:{a.port}'
    out = dict(mode=a.mode, requests=len(wires), tags={t: tags.count(t) for t in set(tags)})
    try:
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f'server exited rc={proc.returncode}')
            try:
                urllib.request.urlopen(base + '/health', timeout=5)
                break
            except Exception:
                if time.time() - t0 > 1200:
                    raise TimeoutError('startup')
                time.sleep(5)
        out['startup_s'] = round(time.time() - t0, 1)
        order = list(range(len(wires)))
        p1, s1 = run_pass(base, wires, order)
        p2, s2 = run_pass(base, wires, order[::-1])
        out.update(pass1_s=round(s1, 1), pass2_s=round(s2, 1))
        same = {t: [0, 0] for t in set(tags)}
        errors = 0
        for i in order:
            if 'error' in p1[i] or 'error' in p2[i]:
                errors += 1
                continue
            same[tags[i]][1] += 1
            same[tags[i]][0] += p1[i]['content'] == p2[i]['content']
        out.update(errors=errors, identical={t: f'{v[0]}/{v[1]}' for t, v in same.items()},
                   completion_tokens=sum(p1[i].get('completion_tokens', 0) for i in order),
                   sample_errors=[p1[i].get('error') or p2[i].get('error') for i in order
                                  if 'error' in p1[i] or 'error' in p2[i]][:3],
                   pass1=p1, pass2=p2, tag_of=tags)
    except Exception as e:
        out['failure'] = f'{type(e).__name__}: {e}'
    finally:
        proc.terminate()
        try:
            proc.wait(60)
        except subprocess.TimeoutExpired:
            proc.kill()
        with open(a.out, 'x') as f:
            json.dump(out, f, ensure_ascii=False)
        print(json.dumps({k: v for k, v in out.items() if k not in ('pass1', 'pass2', 'tag_of')}))


if __name__ == '__main__':
    main()

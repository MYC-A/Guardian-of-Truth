"""Run the escalation probe on a vLLM server (production server flags, normal mode), N independent passes.

    python run.py --python <venv python> --model <dir> --requests requests.json --passes 3 --out probe_out.json
requests.json: [{"key": ..., "messages": [...]}]; built locally by build.py (no gold inside).
"""
import argparse
import json
import os
import subprocess
import time
import urllib.request

from replay import post, run_pass  # noqa: E402  (same directory on the server)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--python', required=True)
    ap.add_argument('--model', required=True)
    ap.add_argument('--requests', required=True)
    ap.add_argument('--passes', type=int, default=3)
    ap.add_argument('--out', required=True)
    ap.add_argument('--port', type=int, default=18124)
    a = ap.parse_args()
    reqs = json.load(open(a.requests))
    served = 'guardian-probe'
    wires = [dict(model=served, messages=r['messages'], temperature=0, max_tokens=1500,
                  response_format=dict(type='json_object'), chat_template_kwargs=dict(enable_thinking=False))
             for r in reqs]
    env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1')
    for k in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD'):
        env.pop(k, None)
    cmd = [a.python, '-m', 'vllm.entrypoints.openai.api_server', '--model', a.model, '--tokenizer', a.model,
           '--served-model-name', served, '--host', '127.0.0.1', '--port', str(a.port),
           '--max-model-len', '32768', '--max-num-seqs', '16', '--gpu-memory-utilization', '0.88',
           '--generation-config', 'vllm', '--chat-template-content-format', 'string',
           '--enable-prefix-caching', '--enable-chunked-prefill', '--dtype', 'bfloat16', '--kv-cache-dtype', 'auto']
    log = open(a.out + '.server.log', 'w')
    t0 = time.time()
    proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f'http://127.0.0.1:{a.port}'
    out = dict(requests=len(wires), keys=[r['key'] for r in reqs], passes=[])
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
        for p in range(a.passes):
            res, s = run_pass(base, wires, order if p % 2 == 0 else order[::-1])
            out['passes'].append(dict(seconds=round(s, 1), results=[res[i] for i in order]))
    except Exception as e:
        out['failure'] = f'{type(e).__name__}: {e}'
    finally:
        proc.terminate()
        try:
            proc.wait(60)
        except subprocess.TimeoutExpired:
            proc.kill()
    json.dump(out, open(a.out, 'w'), ensure_ascii=False)
    print(json.dumps({k: v for k, v in out.items() if k != 'passes'} | dict(pass_s=[p['seconds'] for p in out['passes']]))[:600])


if __name__ == '__main__':
    main()

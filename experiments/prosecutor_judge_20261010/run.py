"""Server runner: one vLLM server (production flags), per pass: prosecutor on all rows of that pass, code check,
judge on checked accusations.
    PYTHONPATH=<code> python -m experiments.prosecutor_judge_20261010.run --python <venv> --model <dir> --rows rows.json --out out.json
"""
import argparse
import json
import os
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from experiments.escalation_probe_20261010.probe import parse_answer
from experiments.prosecutor_judge_20261010.pj import check_accusation, judge_messages, prosecutor_messages

SERVED = 'guardian-pj'


def post(url, body, timeout=900):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def call_all(base, message_lists, workers=16):
    def one(m):
        try:
            d = post(base + '/v1/chat/completions', dict(
                model=SERVED, messages=m, temperature=0, max_tokens=1200, response_format=dict(type='json_object'),
                chat_template_kwargs=dict(enable_thinking=False)))
            return dict(content=d['choices'][0]['message']['content'], finish=d['choices'][0]['finish_reason'],
                        prompt_tokens=d['usage']['prompt_tokens'], completion_tokens=d['usage']['completion_tokens'])
        except Exception as e:
            return dict(error=f'{type(e).__name__}: {str(e)[:300]}')
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, message_lists))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--python', required=True)
    ap.add_argument('--model', required=True)
    ap.add_argument('--rows', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--port', type=int, default=18125)
    a = ap.parse_args()
    rows = json.load(open(a.rows))
    env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1')
    for k in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD'):
        env.pop(k, None)
    cmd = [a.python, '-m', 'vllm.entrypoints.openai.api_server', '--model', a.model, '--tokenizer', a.model,
           '--served-model-name', SERVED, '--host', '127.0.0.1', '--port', str(a.port),
           '--max-model-len', '32768', '--max-num-seqs', '16', '--gpu-memory-utilization', '0.88',
           '--generation-config', 'vllm', '--chat-template-content-format', 'string',
           '--enable-prefix-caching', '--enable-chunked-prefill', '--dtype', 'bfloat16', '--kv-cache-dtype', 'auto']
    log = open(a.out + '.server.log', 'w')
    t0 = time.time()
    proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f'http://127.0.0.1:{a.port}'
    out = dict(rows=len(rows), passes=[])
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
        for p in range(max(r['passes'] for r in rows)):
            idx = [i for i, r in enumerate(rows) if r['passes'] > p]
            if p % 2:
                idx = idx[::-1]
            t = time.time()
            pros = call_all(base, [prosecutor_messages(rows[i]['prompt'], rows[i]['turn']) for i in idx])
            s1 = time.time() - t
            accs, checks = [], []
            for i, res in zip(idx, pros):
                acc = parse_answer(res.get('content')) if 'error' not in res else None
                ok, why = check_accusation(rows[i]['prompt'], rows[i]['turn'], acc) if acc is not None else (False, 'unparsed')
                accs.append(acc)
                checks.append((ok, why))
            jidx = [j for j, (ok, _) in enumerate(checks) if ok]
            t = time.time()
            judges = call_all(base, [judge_messages(rows[idx[j]]['prompt'], rows[idx[j]]['turn'], accs[j]) for j in jidx])
            s2 = time.time() - t
            jmap = dict(zip(jidx, judges))
            out['passes'].append(dict(prosecutor_s=round(s1, 1), judge_s=round(s2, 1), items=[
                dict(key=rows[i]['key'], prosecutor=pros[j], check=checks[j][1], judge=jmap.get(j))
                for j, i in enumerate(idx)]))
            print(f'pass {p}: rows {len(idx)} prosecutor {s1:.0f}s accusations {len(jidx)} judge {s2:.0f}s', flush=True)
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

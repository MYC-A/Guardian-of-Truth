"""10-minute engine probe: does the served model actually scale with parallel requests?

Measures aggregate decode throughput for 1, 2, 4, 8 (,16) concurrent identical-shape
requests on an already running loopback OpenAI-compatible server (llama.cpp or vLLM).
If tokens/s at N=8 is < 2x tokens/s at N=1, the engine, not the client, is the
bottleneck and queue/thread changes cannot fix B2 wall time.

    python scripts/engine_probe.py --base http://127.0.0.1:PORT --model MODEL --api-key-env KEY_VAR
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import time
import urllib.request

TEXT = ('Ниже журнал обращения клиента. ' * 120)


def post(base, payload, key, timeout=900):
    request = urllib.request.Request(base + '/v1/chat/completions', json.dumps(payload).encode(),
                                     {'Content-Type': 'application/json', **({'Authorization': 'Bearer ' + key} if key else {})})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.load(response)


def one(base, model, key, tokens, salt):
    payload = dict(model=model, temperature=0, max_tokens=tokens, ignore_eos=True,
                   chat_template_kwargs=dict(enable_thinking=False),
                   messages=[dict(role='user', content=f'[{salt}] {TEXT}\nПерескажи подробно, нумеруя пункты.')])
    start = time.monotonic()
    data = post(base, payload, key)
    return time.monotonic() - start, data['usage']['completion_tokens'], data['usage']['prompt_tokens']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--api-key-env')
    parser.add_argument('--tokens', type=int, default=256)
    parser.add_argument('--levels', default='1,2,4,8')
    parser.add_argument('--output')
    options = parser.parse_args()
    key = os.environ.get(options.api_key_env) if options.api_key_env else None
    one(options.base, options.model, key, 16, 'warmup')
    results = []
    for n in [int(x) for x in options.levels.split(',')]:
        start = time.monotonic()
        with ThreadPoolExecutor(n) as pool:
            parts = list(pool.map(lambda i: one(options.base, options.model, key, options.tokens, f'{n}-{i}'), range(n)))
        wall = time.monotonic() - start
        generated = sum(p[1] for p in parts)
        results.append(dict(concurrency=n, wall=round(wall, 2), generated=generated,
                            aggregate_tps=round(generated / wall, 2),
                            per_stream_tps=round(sum(p[1] / p[0] for p in parts) / n, 2)))
        print(json.dumps(results[-1]), flush=True)
    base_tps = results[0]['aggregate_tps']
    for r in results:
        r['scaling_vs_1'] = round(r['aggregate_tps'] / base_tps, 2)
    verdict = ('ENGINE_DOES_NOT_BATCH' if results[-1]['scaling_vs_1'] < 2 else 'ENGINE_SCALES')
    summary = dict(results=results, verdict=verdict)
    print(json.dumps(summary, indent=2))
    if options.output:
        with open(options.output, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2)


if __name__ == '__main__':
    main()

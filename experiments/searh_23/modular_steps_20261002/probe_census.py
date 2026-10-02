"""§7 API model census: ONE short chat probe per model (availability only).

Probes verify TRANSPORT + JSON mode, not quality. Reasoning models (gpt-oss,
nemotron) may return empty content when the output budget is consumed by
reasoning: exactly ONE justified re-probe with a larger limit is allowed per
assignment §7 (reason recorded). glm-5.3-flash stays 402-blocked (breaker
OPEN_PERMANENT, no probe spent). Mistral is the working production channel
(existing receipts; no new probe). Results: model_census.json.
"""
import json
import time

from modular_common import RESULTS, Budget

MODELS = [
    ('ollama.com', 'gemma4:31b', 'gemma'),
    ('ollama.com', 'gpt-oss:20b', 'gpt-oss'),
    ('ollama.com', 'gpt-oss:120b', 'gpt-oss'),
    ('ollama.com', 'nemotron-3-nano:30b', 'nemotron'),
    ('ollama.com', 'nemotron-3-super', 'nemotron'),
    ('ollama.com', 'nemotron-3-ultra', 'nemotron'),
    ('aihorde', 'google/gemma-4-31b', 'gemma'),
]
PROBE_TASK = 'Reply with exactly the JSON {"ok": true} and nothing else.'


def probe(llm, model, max_tokens):
    began = time.monotonic()
    answer = llm.chat(model, [{'role': 'user', 'content': PROBE_TASK}],
                      max_tokens=max_tokens, temperature=0, json_mode=True,
                      transport_retries=0, caller='channel-probe')
    elapsed = time.monotonic() - began
    content = answer.get('content') or ''
    return {'content_head': content[:220], 'content_len': len(content),
            'content_empty': not content.strip(),
            'usage': answer.get('usage') or {}, 'cached': bool(answer.get('cached')),
            'error': answer.get('error'), 'error_type': answer.get('error_type'),
            'http_status': answer.get('http_status'), 'elapsed_s': round(elapsed, 2),
            'max_tokens': max_tokens}


def main():
    budget = Budget('reviewer_repair')
    llm = budget.install()
    census = {'schema': 'model-census/1',
              'note': 'availability probes only; smoke success is NOT a quality result; '
                      'one probe per model, one justified re-probe for empty reasoning outputs',
              'excluded': {'glm-5.3-flash': '402 OPEN_PERMANENT (block until quota/config change); '
                                           'no probe spent, excluded from quality ranking'},
              'mistral': {'model': llm.DEFAULT_MISTRAL_MODEL,
                          'status': 'WORKING (production receipts: negative/temporal/atomic pilots)',
                          'probe': 'not spent — existing receipts'},
              'models': []}
    for provider, model, family in MODELS:
        entry = {'provider': provider, 'model': model, 'family': family,
                 'independent_family': family not in ('gemma',) or model == 'gemma4:31b'}
        first = probe(llm, model, 500)
        entry['probe_1'] = first
        if first['content_empty'] and not first['error']:
            # justified single re-probe: reasoning tokens may consume a small budget
            entry['reprobe_reason'] = 'empty content at max_tokens=500 (reasoning budget)'
            entry['probe_2'] = probe(llm, model, 3000)
        census['models'].append(entry)
        print(json.dumps({'model': model, 'empty': entry['probe_1']['content_empty'],
                          'reprobe': 'probe_2' in entry,
                          'error': first['error_type']}, ensure_ascii=False))
    out = RESULTS / 'model_census.json'
    out.write_text(json.dumps(census, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print('written', out)


if __name__ == '__main__':
    main()

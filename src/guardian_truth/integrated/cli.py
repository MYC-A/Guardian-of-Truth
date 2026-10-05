"""guardian-review: run the integrated reviewer on unseen inputs (no labels, no row-ID mapping).

  guardian-review INPUT.json|INPUT.jsonl [--profile integrated] [--provider mistral|ollama] [--model M]
                  [--cache-dir DIR] [--offline] [--no-model] [--max-calls N] [--attempt K] [--output OUT.jsonl]

INPUT holds objects with 'prompt' and 'response' (other keys are ignored and never read by review()).
--offline: zero-HTTP replay; a cache miss fails loudly (NetworkTripwire).
--no-model: code-only path (guard + packet + relations); the model step is NOT_EXECUTED -> UNKNOWN unless
the guard proves an error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import PROFILES, ReviewConfig, review
from .transport import Transport

DEFAULT_MODELS = {'mistral': 'ministral-14b-2512', 'ollama': 'gemma4:31b'}


def _inputs(path):
    text = Path(path).read_text(encoding='utf-8')
    if path.endswith('.jsonl'):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    return data if isinstance(data, list) else [data]


def main(argv=None):
    ap = argparse.ArgumentParser(prog='guardian-review', description=__doc__.split('\n')[0])
    ap.add_argument('input')
    ap.add_argument('--profile', choices=sorted(PROFILES), default='integrated')
    ap.add_argument('--provider', choices=sorted(DEFAULT_MODELS), default='mistral')
    ap.add_argument('--model')
    ap.add_argument('--budget-bytes', type=int, default=20000)
    ap.add_argument('--cache-dir', default='.guardian_cache')
    ap.add_argument('--offline', action='store_true')
    ap.add_argument('--no-model', action='store_true')
    ap.add_argument('--max-calls', type=int)
    ap.add_argument('--attempt', type=int, default=0)
    ap.add_argument('--output')
    ap.add_argument('--full', action='store_true', help='emit the full trace instead of the compact result')
    a = ap.parse_args(argv)
    model = a.model or DEFAULT_MODELS[a.provider]
    cfg = ReviewConfig.profile(a.profile, provider=a.provider, model=model, budget_bytes=a.budget_bytes, attempt=a.attempt)
    client = None if a.no_model else Transport(a.provider, model, a.cache_dir, offline=a.offline, max_calls=a.max_calls)
    out = open(a.output, 'x', encoding='utf-8') if a.output else sys.stdout
    try:
        for item in _inputs(a.input):
            res = review(item['prompt'], item['response'], cfg, client=client)
            if not a.full:
                gaps = len(res['gaps'])
                res = {k: res[k] for k in ('binary', 'final_decision', 'projection', 'proof_status', 'decision_owner',
                                           'reasons', 'source_sha256', 'cost')}
                res['gap_count'] = gaps
            out.write(json.dumps(res, ensure_ascii=False) + '\n')
    finally:
        if out is not sys.stdout:
            out.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

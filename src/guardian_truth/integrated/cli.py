"""guardian-review: run the integrated reviewer on unseen inputs (no labels, no row-ID mapping).

  guardian-review INPUT.json|INPUT.jsonl [--profile guard_adm2] [--provider mistral|ollama] [--model M]
                  [--cache-dir DIR] [--offline] [--no-model] [--max-calls N] [--attempt K] [--output OUT.jsonl]
                  [--repair r_fix]

INPUT holds objects with 'prompt' and 'response' (other keys are ignored and never read by review()).
--offline: zero-HTTP replay; a cache miss fails loudly (NetworkTripwire).
--no-model: code-only path (guard + packet + relations); the model step is NOT_EXECUTED -> UNKNOWN unless
the guard proves an error.
--repair r_fix: OPT-IN research profile (docs/universal_repair_v2/FINAL_DECISION.md): the guard reviewer plus the
repaired DF/Ems/AT components and verifier (repair.v5, arm R_fix). Default stays --repair none (unchanged output).
The confirmation component CB is NOT run in r_fix (shadow only). The output carries packet coverage, the components
that ran, every candidate's verification status and the decision owner, so a NO_ERROR is never silent about gaps.
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
    ap.add_argument('--profile', choices=sorted(PROFILES), default='guard_adm2')
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
    ap.add_argument('--repair', choices=['none', 'r_fix'], default='none', help='opt-in research repair profile (default none)')
    a = ap.parse_args(argv)
    if a.repair != 'none':
        return _repair_main(a)
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


def _repair_main(a):
    from ..repair.clients import ReadThrough
    from ..repair.v5 import ARMS, decide, run_v5
    from ..verification.pipeline import packet_for
    if a.no_model:
        raise SystemExit('--repair needs a model (use --offline for cache-only replay)')
    model = a.model or DEFAULT_MODELS[a.provider]
    tr = Transport(a.provider, model, a.cache_dir, offline=a.offline, max_calls=a.max_calls)
    client = ReadThrough(a.provider, model, [], live=tr)
    out = open(a.output, 'x', encoding='utf-8') if a.output else sys.stdout
    try:
        for item in _inputs(a.input):
            row = dict(id=item.get('id', ''), prompt=item['prompt'], response=item['response'])
            rec = run_v5(row, client, flags=ARMS['R_fix'], provider=a.provider, model=model, budget=a.budget_bytes,
                         attempt=a.attempt, with_cb=False)
            binary, acc = decide(rec)
            p = packet_for(row, a.budget_bytes)
            res = dict(profile='repair_r_fix', binary=binary, decision_owner=(acc or {}).get('origin'), accusation=acc,
                       base_reviewer=dict(final=rec['A'].get('final'), guard_error=rec['A'].get('guard_error')),
                       coverage=(p or {}).get('coverage'), triggers=rec.get('triggers'),
                       components={k: v.get('admission') for k, v in (rec.get('components') or {}).items()},
                       candidates=[dict(component=x['component'], kind=x['candidate'].get('kind'), target_id=x['candidate'].get('target_id'),
                                        verification=x.get('verification_status'), certificate=bool(x['candidate'].get('certificate')))
                                   for x in rec.get('pool') or []],
                       cb='NOT_RUN_SHADOW', skipped=rec.get('skipped'))
            out.write(json.dumps(rec if a.full else res, ensure_ascii=False, default=str) + '\n')
    finally:
        if out is not sys.stdout:
            out.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

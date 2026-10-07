"""Offline recompute for local A100 runs (zero network, zero model).

Recomputes every binary metric and counter from the saved run records alone
(outputs/guardian_local_a100/<backend>/<model>/runs/*.jsonl) — the records
carry the decisions, receipts and usage; nothing is re-derived from the model.

Usage:
  python -m experiments.guardian_local_a100.recompute --backend vllm \
      --model-id 'ministral-3-14b-instruct-2512@29439f81c2be:bf16:vllm-0.31.0' \
      [--sets dev,devT,frozen,contrast,valid46,lb_long,lb2_long,lb3_long,ext_tau2,hold_tau2h,hold_holdout2] \
      [--out outputs/guardian_local_a100/<backend>/<model>/recompute.json]

Exit code 0 always; the JSON carries per-set summaries and row-level outcomes.
"""
import argparse
import json
from pathlib import Path

from .score_local import score_set
from .run_local import OUTROOT

DEFAULT_SETS = ('dev,devT,frozen,contrast,valid46,lb_long,lb2_long,lb3_long,'
                'ext_tau2,hold_tau2h,hold_holdout2')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--backend', required=True, choices=('vllm', 'llamacpp'))
    ap.add_argument('--model-id', required=True)
    ap.add_argument('--sets', default=DEFAULT_SETS)
    ap.add_argument('--out')
    a = ap.parse_args()
    runs_dir = OUTROOT / a.backend / a.model_id.replace('/', '_') / 'runs'
    out = {}
    for s in [x for x in a.sets.split(',') if x]:
        try:
            res, rows = score_set(s, runs_dir)
        except Exception as e:
            out[s] = dict(error=f'{type(e).__name__}: {e}'[:200])
            continue
        if res:
            out[s] = res
    payload = dict(model=a.model_id, backend=a.backend, network_calls=0,
                   source='runs/*.jsonl saved records only', summary=out)
    path = Path(a.out) if a.out else OUTROOT / a.backend / a.model_id.replace('/', '_') / 'recompute.json'
    if path.exists():
        path = path.with_name(path.stem + '_2.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    for s, res in out.items():
        if isinstance(res, dict) and 'error' not in res:
            for k, m in res.items():
                print(f"{s:14s} {k:10s} TP{m['tp']} FP{m['fp']} FN{m['fn']} TN{m['tn']} F1={m['f1']} "
                      f"tech={m['technical']} unlabelled={m.get('executed_unlabelled', 0)}")
        else:
            print(f"{s:14s} {res}")
    print('RECOMPUTE_WRITTEN', path)


if __name__ == '__main__':
    main()

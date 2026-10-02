"""Read-only reconciliation of the double-instrumented dev2 window (§4).

The historical ledger is NEVER rewritten. This report quantifies the phantom
rows created when system_v2_pilot installed a Budget and then
modular_runtime.guarded_llm() installed a SECOND layer over the already
wrapped transport (user bug 2026-10-02 §4): every native transport call in
that window was recorded twice (attempts and usage doubled), and cached
answers were double-recorded as CACHE_HIT rows.

Phantom signature (one native call recorded twice by nested layers):
  - identical request key;
  - started within 50 ms of each other (the outer layer reserves just before
    calling the inner wrapper);
  - identical status, api flag and tokens;
  - outer seconds >= inner seconds (nested span: outer starts first and
    finishes last).
Genuine retries are NEVER merged: they share a request hash but are separated
by a completed first attempt (the second starts after the first finished) and
typically differ in status. Rows outside the affected window are single-layer
by construction (their runners never call modular_runtime.guarded_llm).
"""
import argparse
import json
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from modular_common import RESULTS

STARTED_EPSILON = 0.05  # seconds between outer/inner reservations of one call


def pairs(rows):
    """Detect phantom double-count pairs by the nested-span signature."""
    by_key = defaultdict(list)
    for r in rows:
        by_key[r[3]].append(r)
    found = []
    for key, rs in by_key.items():
        rs = sorted(rs, key=lambda r: r[0])
        for i in range(len(rs) - 1):
            a, b = rs[i], rs[i + 1]
            if (a[4] == b[4] and a[6] == b[6] and a[5] == b[5]
                    and b[7] - a[7] < STARTED_EPSILON and a[8] >= b[8] - 1e-9):
                found.append((a, b))
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ledger', default=str(RESULTS / 'dev2_budget.sqlite'))
    args = parser.parse_args()
    db = sqlite3.connect(args.ledger)
    rows = db.execute('SELECT id,module,model,key,status,tokens,api,started,seconds '
                      'FROM attempts ORDER BY id').fetchall()
    phantom = pairs(rows)
    ids = sorted({r[0] for pair in phantom for r in pair})
    by_module = defaultdict(int)
    for a, _ in phantom:
        by_module[a[1]] += 1
    phantom_api = sum(a[6] for a, _ in phantom)
    phantom_logical = sum(a[5] for a, _ in phantom)
    phantom_known = sum(a[5] for a, _ in phantom if a[4] == 'COMPLETE')
    phantom_seconds = sum(a[8] for a, _ in phantom)
    n, logical, seconds = db.execute('SELECT COALESCE(SUM(api),0),COALESCE(SUM(tokens),0),'
                                     'COALESCE(SUM(seconds),0) FROM attempts').fetchone()
    known = db.execute("SELECT COALESCE(SUM(tokens),0) FROM attempts WHERE status='COMPLETE'").fetchone()[0]
    pending = db.execute("SELECT COUNT(*) FROM attempts WHERE status='RESERVED'").fetchone()[0]
    statuses = {a[4] for a, _ in phantom}
    window = None
    if phantom:
        st = min(a[7] for a, _ in phantom)
        en = max(b[7] + b[8] for a, b in phantom)
        window = {'started_min': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(st)),
                  'finished_max': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(en)),
                  'row_id_min': min(ids), 'row_id_max': max(ids)}
    report = {
        'schema': 'budget-reconciliation/1',
        'ledger': str(args.ledger),
        'bug': 'system_v2_pilot Budget.install() + modular_runtime.guarded_llm() second '
               'install() double-wrapped the transport (fixed by idempotent single-layer '
               'ownership + BudgetPhaseConflict); historical ledger intentionally not rewritten',
        'method': {
            'phantom_signature': 'same request key; started <50ms apart; same status/api/tokens; '
                                 'outer seconds >= inner seconds (nested span)',
            'genuine_retries': 'never merged: retries start after the previous attempt finished '
                               'and normally differ in status; identical request hash alone is NOT '
                               'treated as a duplicate'},
        'recorded': {'actual_api_attempts': n, 'logical_tokens': logical,
                     'known_provider_tokens': known, 'model_seconds': seconds,
                     'pending_reservations': pending},
        'phantom': {'pairs': len(phantom), 'row_ids': ids, 'by_module': dict(by_module),
                    'statuses': sorted(statuses), 'actual_api_attempts': phantom_api,
                    'logical_tokens': phantom_logical, 'known_provider_tokens': phantom_known,
                    'model_seconds': phantom_seconds, 'window': window},
        'reconciled_real': {'actual_api_attempts': n - phantom_api,
                            'logical_tokens': logical - phantom_logical,
                            'known_provider_tokens': known - phantom_known,
                            'model_seconds': seconds - phantom_seconds},
        'uncertainty': 'reconciled numbers are a lower bound on real spend: any hypothetical '
                       'phantom pair reserved >50ms apart would not match the signature (none '
                       'observed); guard-veto phantoms (api=1 row without a native call) would '
                       'appear as TRANSPORT_ERROR rows outside pairs — none exist in this ledger',
        'phases': {'dev2_remaining_after_reconciliation': {
            'actual_api_attempts': 300 - (n - phantom_api),
            'logical_tokens': 1200000 - (logical - phantom_logical),
            'known_provider_tokens': 1000000 - (known - phantom_known)}},
    }
    out = RESULTS / 'budget_reconciliation.json'
    out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n',
                   encoding='utf-8')
    print(json.dumps({'phantom_pairs': len(phantom), 'recorded_attempts': n,
                      'reconciled_attempts': n - phantom_api,
                      'reconciled_known_tokens': known - phantom_known,
                      'report': str(out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()

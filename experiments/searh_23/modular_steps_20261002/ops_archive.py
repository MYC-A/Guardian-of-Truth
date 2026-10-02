"""Archive safe resource receipts and completed native metadata, no env dump."""
import json
import sqlite3
from pathlib import Path

folder = Path('/workspace/guardian/results/modular_steps_20261002')
with sqlite3.connect(folder / 'pilot_budget.sqlite') as db:
    db.row_factory = sqlite3.Row
    rows = [dict(r) for r in db.execute('SELECT * FROM attempts ORDER BY id')]
(folder / 'pilot_budget_ledger.json').write_text(json.dumps(rows, indent=2) + '\n')
summary = {'actual_api_attempts': sum(r['api'] for r in rows), 'logical_tokens_or_unknown_usage_bound': sum(r['tokens'] for r in rows),
           'model_seconds': sum(r['seconds'] for r in rows), 'pending': sum(r['status'] == 'RESERVED' for r in rows)}
for name in ('selfcheck_recovery', 'native_claim_pilot'):
    path = folder / name / 'status.json'
    if path.exists():
        obj = json.loads(path.read_text())
        summary[name] = {k: v for k, v in obj.items() if k != 'budget'}
(folder / 'budget_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary))

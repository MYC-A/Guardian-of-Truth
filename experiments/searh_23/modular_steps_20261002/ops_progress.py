"""Compact progress: no raw model text, keys or repeated health probes."""
import json
from pathlib import Path
import sqlite3

root = Path('/workspace/guardian/results/modular_steps_20261002')
for path in root.glob('*/status.json'):
    value = json.loads(path.read_text())
    print(json.dumps({'job': path.parent.name, 'state': value.get('state'), 'done': value.get('done'), 'total': value.get('total')}))
dbpath = root / 'pilot_budget.sqlite'
if dbpath.exists():
    with sqlite3.connect(str(dbpath)) as db:
        print(json.dumps({'actual_api_attempts_tokens_seconds_pending': db.execute("SELECT SUM(api),SUM(tokens),SUM(seconds),SUM(status='RESERVED') FROM attempts").fetchone()}))

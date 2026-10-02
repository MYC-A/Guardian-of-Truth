"""One bounded inspection of a specific live/terminal job, no model polling."""
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

revision = sys.argv[1]
if not re.fullmatch('[0-9a-f]{8,40}', revision):
    raise ValueError('commit SHA required')
folder = Path('/workspace/guardian/repos/source-search-' + revision) / 'outputs/searh_23/source_search_20261002/comparison_v3'
program = 'guardian_source_compare_' + revision[:8]
process = subprocess.run(['supervisorctl', 'status', program], capture_output=True, text=True)
result = {'process': process.stdout.strip(), 'handle_exists': 'ERROR' not in process.stdout}
journal = folder / 'predictions.jsonl'
if journal.exists():
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    result['records'] = len(rows)
    result['recent'] = [{k: r.get(k) for k in ('case_id', 'mode', 'decision', 'stop_reason')} for r in rows[-4:]]
    result['all_terminal_reasons'] = sorted({r['stop_reason'] for r in rows})
database = folder / 'transport/budget.sqlite'
if database.exists():
    db = sqlite3.connect(database)
    result['budget'] = db.execute('SELECT COUNT(*),COALESCE(SUM(known_tokens),0),COALESCE(SUM(unknown_bound),0),COALESCE(SUM(seconds),0) FROM attempts').fetchone()
    db.close()
if (folder / 'status.json').exists():
    result['terminal_status'] = json.loads((folder / 'status.json').read_text())
print(json.dumps(result))

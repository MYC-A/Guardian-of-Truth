"""Preserve a stopped technical pilot and carry its budget into recovery."""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import zipfile

base = Path('/workspace/guardian')
old = base / 'repos/source-search-6b73ff24/outputs/searh_23/source_search_20261002/comparison_v3'
handle = subprocess.run(['supervisorctl', 'status', 'guardian_source_compare_6b73ff24'], capture_output=True, text=True).stdout
if 'STOPPED' not in handle:
    raise RuntimeError('old technical job is not confirmed stopped; do not copy a live budget')
phase = base / 'results/source-search-api-phase-20261002'
phase.mkdir(parents=True, exist_ok=True)
source_db, target_db = old / 'transport/budget.sqlite', phase / 'budget.sqlite'
if target_db.exists():
    raise RuntimeError('shared recovery budget already exists; never reset or overwrite it')
with closing(sqlite3.connect(source_db)) as source, closing(sqlite3.connect(target_db)) as target:
    source.backup(target)
    before = source.execute('SELECT COUNT(*),SUM(known_tokens),SUM(unknown_bound) FROM attempts').fetchone()
    target.execute("UPDATE attempts SET status='STOPPED_USAGE_UNKNOWN_BOUND_RETAINED' WHERE status='RESERVED'")
    target.commit()
    after = target.execute('SELECT COUNT(*),SUM(known_tokens),SUM(unknown_bound) FROM attempts').fetchone()
    if before != after:
        raise RuntimeError('budget totals changed during recovery migration')
    budget_rows = [dict(zip(['id','request_sha','status','known_tokens','unknown_bound','seconds'], r))
                   for r in target.execute('SELECT * FROM attempts')]
shutil.copytree(old / 'transport/cache', phase / 'cache', dirs_exist_ok=False)
shutil.copy2(old / 'transport/attempts.jsonl', phase / 'attempts.jsonl')
receipt = {'state': 'TECHNICAL_STOP_PHASE_CONTRACT_DEFECT', 'old_handle': handle.strip(),
    'old_results_preserved': True, 'gold_opened_for_recovery': False,
    'budget_before': before, 'budget_after': after, 'budget_reset': False,
    'recovery': 'Explicit SEARCH role and no final schema before JUDGE; separate V4 protocol',
    'approved_cap': {'tokens': 500000, 'attempts': 150}}
(old / 'status.json').write_text(json.dumps(receipt, indent=2))
(phase / 'migration.json').write_text(json.dumps(receipt, indent=2))
(phase / 'budget_migration_rows.json').write_text(json.dumps(budget_rows, indent=2))
archive = base / 'results/source-search-v3-technical-stop.zip'
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as file:
    for path in old.rglob('*'):
        if path.is_file():
            file.write(path, Path('comparison_v3') / path.relative_to(old))
    file.write(phase / 'migration.json', 'phase/migration.json')
    file.write(phase / 'budget_migration_rows.json', 'phase/budget_migration_rows.json')
print(json.dumps(receipt))

"""Launch one recovery in its own immutable sparse checkout."""
import json
from pathlib import Path
import subprocess

revision = '19c1f793'
base = Path('/workspace/guardian')
repo = base / 'repos/Guardian-of-Truth'
checkout = base / ('repos/modular-step2-4-' + revision)
out = base / 'results/modular_steps_20261002'
subprocess.run(['git', '-C', str(repo), 'fetch', 'origin', 'research/modular-step2-4-20261002'], check=True)
if not checkout.exists():
    subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '--detach', '--no-checkout', str(checkout), revision], check=True)
    subprocess.run(['git', '-C', str(checkout), 'sparse-checkout', 'set', 'service', 'src',
        'experiments/searh_23/three_architectures', 'experiments/searh_23/hybrid_service_v1',
        'experiments/searh_23/system_research_v2', 'experiments/searh_23/system_integration_v1',
        'experiments/searh_23/modular_steps_20261002'], check=True)
    subprocess.run(['git', '-C', str(checkout), 'checkout', revision], check=True)
worker = out / 'native_sequence.py'
worker.write_text('''import json, subprocess
from pathlib import Path
base = Path('/workspace/guardian')
checkout = base / 'repos/modular-step2-4-19c1f793'
records = []
for script in ('selfcheck_recovery.py', 'native_claim_pilot.py'):
    result = subprocess.run([str(base / 'modular_venv/bin/python'), '-u', 'experiments/searh_23/modular_steps_20261002/' + script], cwd=checkout)
    records.append({'script': script, 'exit_code': result.returncode})
(base / 'results/modular_steps_20261002/native_sequence_status.json').write_text(json.dumps(records))
''')
with (out / 'native_sequence.log').open('a') as log:
    p = subprocess.Popen([str(base / 'modular_venv/bin/python'), '-u', str(worker)], cwd=checkout,
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
receipt = {'job': 'native_sequence', 'pid': p.pid, 'pinned_revision': revision, 'checkout': str(checkout),
           'isolated_environment_change': 'transformers4.57.6/huggingface-hub0.36.2/tokenizers0.22.2/sentencepiece0.2.1'}
(out / 'launch_recovery.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))

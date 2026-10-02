"""Launch one recovery in its own immutable sparse checkout."""
import json
from pathlib import Path
import subprocess

revision = '563d5b99'
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
with (out / 'selfcheck_recovery.log').open('a') as log:
    p = subprocess.Popen([str(base / 'modular_venv/bin/python'), '-u',
        'experiments/searh_23/modular_steps_20261002/selfcheck_recovery.py'], cwd=checkout,
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
receipt = {'job': 'selfcheck_recovery', 'pid': p.pid, 'pinned_revision': revision, 'checkout': str(checkout)}
(out / 'launch_recovery.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))

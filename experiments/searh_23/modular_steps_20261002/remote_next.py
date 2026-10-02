"""Create another immutable checkout; preserve processes on previous checkout."""
from pathlib import Path
import subprocess
import json

BASE = Path('/workspace/guardian')
REPO = BASE / 'repos/Guardian-of-Truth'
REVISION = '2b2a06ee'
CHECKOUT = BASE / ('repos/modular-step2-4-' + REVISION)
OUT = BASE / 'results/modular_steps_20261002'
PYTHON = BASE / 'modular_venv/bin/python'


if __name__ == '__main__':
    subprocess.run(['git', '-C', str(REPO), 'fetch', 'origin', 'research/modular-step2-4-20261002'], check=True)
    if not CHECKOUT.exists():
        subprocess.run(['git', '-C', str(REPO), 'worktree', 'add', '--detach', '--no-checkout', str(CHECKOUT), REVISION], check=True)
        subprocess.run(['git', '-C', str(CHECKOUT), 'sparse-checkout', 'set', 'service', 'src',
            'experiments/searh_23/three_architectures', 'experiments/searh_23/hybrid_service_v1',
            'experiments/searh_23/system_research_v2', 'experiments/searh_23/system_integration_v1',
            'experiments/searh_23/modular_steps_20261002'], check=True)
        subprocess.run(['git', '-C', str(CHECKOUT), 'checkout', REVISION], check=True)
    for script in ('translator_pilot.py', 'remote_models.py', 'ccg_recovery.py'):
        name = Path(script).stem
        with (OUT / (name + '_round2.log')).open('a') as log:
            p = subprocess.Popen([str(PYTHON), '-u', str(CHECKOUT / 'experiments/searh_23/modular_steps_20261002' / script)],
                cwd=CHECKOUT, stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True)
        print(json.dumps({'job': name, 'pid': p.pid, 'pinned_revision': REVISION}))

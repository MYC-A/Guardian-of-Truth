"""Immutable pinned checkout with shared budget and independent durable jobs."""
import argparse
from pathlib import Path
import subprocess
import json

BASE = Path('/workspace/guardian')
OUT = BASE / 'results/modular_steps_20261002'


def main(revision):
    repository = BASE / 'repos/Guardian-of-Truth'
    checkout = BASE / ('repos/modular-step2-4-' + revision)
    subprocess.run(['git', '-C', str(repository), 'fetch', 'origin', 'research/modular-step2-4-20261002'], check=True)
    if not checkout.exists():
        subprocess.run(['git', '-C', str(repository), 'worktree', 'add', '--detach', '--no-checkout', str(checkout), revision], check=True)
        subprocess.run(['git', '-C', str(checkout), 'sparse-checkout', 'set', 'service', 'src',
            'experiments/searh_23/three_architectures', 'experiments/searh_23/hybrid_service_v1',
            'experiments/searh_23/system_research_v2', 'experiments/searh_23/system_integration_v1',
            'experiments/searh_23/modular_steps_20261002'], check=True)
        subprocess.run(['git', '-C', str(checkout), 'checkout', revision], check=True)
    python = BASE / 'modular_venv/bin/python'
    subprocess.run([str(python), 'experiments/searh_23/modular_steps_20261002/test_boundaries.py'], cwd=checkout, check=True)
    jobs = [('ccg_pilot.py', []), *[('mechanism_pilots.py', [kind]) for kind in ('v2', 'atomic', 'graph', 'selfcheck', 'triad')]]
    receipt = []
    for script, args in jobs:
        name = args[0] if args else Path(script).stem
        with (OUT / (name + '_' + revision + '.log')).open('a') as log:
            p = subprocess.Popen([str(python), '-u', 'experiments/searh_23/modular_steps_20261002/' + script, *args],
                cwd=checkout, stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True)
        item = {'job': name, 'pid': p.pid, 'pinned_revision': revision, 'checkout': str(checkout)}
        receipt.append(item)
        print(json.dumps(item))
    (OUT / ('launch_' + revision + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('revision')
    main(p.parse_args().revision)

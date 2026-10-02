"""Install only our separate loopback supervisor program, preserve old service."""
from pathlib import Path
import argparse
import json
import socket
import subprocess


def main(revision):
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
    path = Path('/etc/supervisor/conf.d/guardian_modular_20261002.conf')
    if path.exists():
        raise RuntimeError('own_service_config_already_exists_inspect_before_replacing')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 18092))
    config = f'''[program:guardian_modular_20261002]
command={base}/modular_venv/bin/python -m uvicorn service.modular_app:app --host 127.0.0.1 --port 18092
directory={checkout}
autostart=true
autorestart=true
startsecs=3
stopasgroup=true
killasgroup=true
stdout_logfile={out}/modular_service_supervisor.log
stderr_logfile={out}/modular_service_supervisor.err.log
environment=GUARDIAN_MODULAR_CONFIG="modular-structural-v1"
'''
    path.write_text(config)
    subprocess.run(['supervisorctl', 'reread'], check=True)
    subprocess.run(['supervisorctl', 'update', 'guardian_modular_20261002'], check=True)
    receipt = {'program': 'guardian_modular_20261002', 'port': 18092, 'bind': '127.0.0.1',
               'revision': revision, 'checkout': str(checkout), 'old_service_modified': False}
    (out / 'modular_service_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('revision')
    main(p.parse_args().revision)

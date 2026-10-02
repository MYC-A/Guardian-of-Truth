"""Install only our separate loopback supervisor program, preserve old service."""
from pathlib import Path
import argparse
import configparser
import hashlib
import json
import os
import re
import socket
import subprocess


def main(revision, replace_own=False):
    if not re.fullmatch('[0-9a-f]{8,40}', revision):
        raise ValueError('expected_commit_SHA')
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
    resolved_revision = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if not resolved_revision.startswith(revision):
        raise ValueError('immutable_checkout_revision_mismatch')
    path = Path('/etc/supervisor/conf.d/guardian_modular_20261002.conf')
    replaced_revision = None
    if path.exists():
        if not replace_own:
            raise RuntimeError('own_service_config_already_exists_inspect_before_replacing')
        prior_blob = path.read_bytes()
        prior = configparser.ConfigParser(interpolation=None)
        prior.read_string(prior_blob.decode())
        section = 'program:guardian_modular_20261002'
        if prior.sections() != [section]:
            raise ValueError('supervisor_file_has_foreign_program')
        expected_command = f'{base}/modular_venv/bin/python -m uvicorn service.modular_app:app --host 127.0.0.1 --port 18092'
        if prior[section].get('command') != expected_command:
            raise ValueError('own_program_command_changed_inspect_manually')
        old_checkout = Path(prior[section]['directory']).resolve()
        if old_checkout.parent != (base / 'repos').resolve() or not old_checkout.name.startswith('modular-step2-4-'):
            raise ValueError('replacement_outside_own_checkout')
        if prior[section].get('environment') != 'GUARDIAN_MODULAR_CONFIG="modular-structural-v1"':
            raise ValueError('own_default_changed_inspect_manually')
        replaced_revision = subprocess.check_output(['git', '-C', str(old_checkout), 'rev-parse', 'HEAD'], text=True).strip()
        backup = out / 'supervisor_backups' / (hashlib.sha256(prior_blob).hexdigest() + '.conf')
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(prior_blob)
    else:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 18092))
    old_pid = subprocess.check_output(['supervisorctl', 'pid', 'guardian_research'], text=True).strip()
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
    temp = path.with_suffix('.conf.tmp')
    temp.write_text(config)
    os.replace(temp, path)
    subprocess.run(['supervisorctl', 'reread'], check=True)
    subprocess.run(['supervisorctl', 'update', 'guardian_modular_20261002'], check=True)
    receipt = {'program': 'guardian_modular_20261002', 'port': 18092, 'bind': '127.0.0.1',
               'revision': resolved_revision, 'checkout': str(checkout), 'old_service_modified': False,
               'replaced_own_revision': replaced_revision, 'old_service_pid_before': old_pid,
               'old_service_pid_after': subprocess.check_output(['supervisorctl', 'pid', 'guardian_research'], text=True).strip()}
    (out / 'modular_service_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('revision')
    p.add_argument('--replace-own', action='store_true', help='Only the validated isolated modular program may be replaced.')
    args = p.parse_args()
    main(args.revision, args.replace_own)

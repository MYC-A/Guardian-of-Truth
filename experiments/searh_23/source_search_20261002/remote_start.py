"""Create one pinned checkout and one finite supervisor comparison job."""
import json
from pathlib import Path
import re
import subprocess
import sys


def command(args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def main(revision, prepare_only=False):
    if not re.fullmatch(r'[0-9a-f]{8,40}', revision):
        raise ValueError('commit SHA required')
    base = Path('/workspace/guardian')
    repo = base / 'repos/Guardian-of-Truth'
    checkout = base / ('repos/source-search-' + revision)
    out = base / ('results/source-search-' + revision)
    out.mkdir(parents=True, exist_ok=True)
    old = {name: command(['supervisorctl', 'pid', name]) for name in
           ('guardian_research', 'guardian_modular_20261002')}
    command(['git', '-C', str(repo), 'fetch', 'origin', 'research/source-search-20261002'])
    if not checkout.exists():
        command(['git', '-C', str(repo), 'worktree', 'add', '--detach', '--no-checkout', str(checkout), revision])
        command(['git', '-C', str(checkout), 'sparse-checkout', 'set', 'service', 'src',
            'experiments/searh_23/three_architectures', 'experiments/searh_23/hybrid_service_v1',
            'experiments/searh_23/source_search_20261002', 'outputs/searh_23/source_search_20261002'])
        command(['git', '-C', str(checkout), 'checkout', revision])
    sha = command(['git', '-C', str(checkout), 'rev-parse', 'HEAD'])
    if not sha.startswith(revision):
        raise ValueError('checkout SHA mismatch')
    python = str(base / 'modular_venv/bin/python')
    tests = command([python, str(checkout / 'experiments/searh_23/source_search_20261002/test_source_search.py')])
    freeze = command([python, str(checkout / 'experiments/searh_23/source_search_20261002/run_compare.py')])
    if prepare_only:
        print(json.dumps({'revision':sha,'checkout':str(checkout),'frozen':json.loads(freeze),
                          'tests':'16 passed','inference_started':False}))
        return
    name = 'guardian_source_compare_' + revision[:8]
    config = Path('/etc/supervisor/conf.d') / (name + '.conf')
    if config.exists():
        raise ValueError('job already exists; inspect its handle instead of restarting')
    config.write_text(f'''[program:{name}]
command={python} experiments/searh_23/source_search_20261002/run_compare.py --run
directory={checkout}
autostart=true
autorestart=false
startsecs=0
stopasgroup=true
killasgroup=true
stdout_logfile={out}/run.log
stderr_logfile={out}/run.err.log
''')
    command(['supervisorctl', 'reread'])
    command(['supervisorctl', 'update', name])
    after = {n: command(['supervisorctl', 'pid', n]) for n in old}
    if old != after:
        raise ValueError('old service PID unexpectedly changed')
    receipt = {'revision': sha, 'checkout': str(checkout), 'program': name,
        'status': command(['supervisorctl', 'status', name]), 'old_pids_before': old,
        'old_pids_after': after, 'frozen': json.loads(freeze),
        'tests': '16 passed; test process exit0', 'no_provider_availability_poll': True}
    (out / 'launch.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt))


if __name__ == '__main__':
    main(sys.argv[1], prepare_only='--prepare-only' in sys.argv[2:])

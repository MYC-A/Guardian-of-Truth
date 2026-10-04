"""Finite remote benchmark managed by supervisor; no credentials are serialized."""
import argparse
from pathlib import Path
import subprocess
import sys

REPO = Path('/workspace/guardian/repos/Guardian-of-Truth')
WORKTREE = Path('/workspace/guardian/repos/semantic-hybrid-v4-20261004')
PYTHON = '/workspace/guardian/modular_venv/bin/python'
RESULTS = Path('/workspace/guardian/results/semantic-hybrid-v4-20261004')
BRANCH = 'research/semantic-hybrid-v4-20261004'


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, **kwargs)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('phase', choices=['prepare', 'start', 'snapshot'])
    p.add_argument('--model', default='ministral-14b-latest')
    p.add_argument('--provider', default='mistral')
    args = p.parse_args()
    if args.phase == 'prepare':
        run(['git', '-C', str(REPO), 'fetch', 'origin', BRANCH])
        if not WORKTREE.exists():
            run(['git', '-C', str(REPO), 'worktree', 'add', '--detach', str(WORKTREE), 'FETCH_HEAD'])
        print('SOURCE_COMMIT', subprocess.check_output(['git', '-C', str(WORKTREE), 'rev-parse', 'HEAD'], text=True).strip())
        run([PYTHON, str(WORKTREE / 'experiments/research_v3/pilot.py'), 'prepare', '--out', str(RESULTS),
             '--model', args.model, '--provider', args.provider])
    elif args.phase == 'start':
        # Managed finite task: no restart after success/failure and no public port.
        conf = Path('/etc/supervisor/conf.d/guardian_v4_research.conf')
        if conf.exists():
            raise ValueError('EXISTING_MANAGED_TASK_NO_RESTART')
        conf.write_text('[program:guardian_v4_research]\n'
                        'command=' + PYTHON + ' ' + str(WORKTREE / 'experiments/research_v3/pilot.py') +
                        ' run --out ' + str(RESULTS) + '\n'
                        'directory=' + str(WORKTREE) + '\n'
                        'autostart=false\nautorestart=false\nstartsecs=0\n'
                        'redirect_stderr=true\nstdout_logfile=' + str(RESULTS / 'execution.log') + '\n'
                        'stdout_logfile_maxbytes=0\n')
        run(['supervisorctl', 'reread']); run(['supervisorctl', 'update'])
        run(['supervisorctl', 'start', 'guardian_v4_research'])
    else:
        import zipfile
        with zipfile.ZipFile(str(RESULTS) + '.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in RESULTS.rglob('*'):
                if path.is_file() and path.suffix not in ('.tmp', '.log'):
                    archive.write(path, path.relative_to(RESULTS))
        print('SNAPSHOT', str(RESULTS) + '.zip')
        run(['supervisorctl', 'status', 'guardian_v4_research'])

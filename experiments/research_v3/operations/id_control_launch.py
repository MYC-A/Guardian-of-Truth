"""Manage finite development-only controls, sealed before starting HTTP."""
import argparse
from pathlib import Path
import subprocess
import zipfile

TREE = Path('/workspace/guardian/repos/semantic-hybrid-v4-20261004')
PYTHON = '/workspace/guardian/modular_venv/bin/python'

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('phase', choices=['prepare', 'start', 'snapshot'])
    p.add_argument('--control', choices=['graph_ids', 'context_enums'], required=True)
    args = p.parse_args()
    out = Path('/workspace/guardian/results/semantic-hybrid-v4-' + args.control + '-dev-20261004')
    # Adapter supplied separately so the frozen original worktree is unchanged.
    script = '/tmp/guardian_v4_id_controls.py'
    command = [PYTHON, script, 'run', '--control', args.control, '--out', str(out)]
    name = 'guardian_v4_' + args.control
    if args.phase == 'prepare':
        subprocess.run([PYTHON, script, 'prepare', '--control', args.control, '--out', str(out)], check=True)
    elif args.phase == 'start':
        conf = Path('/etc/supervisor/conf.d/' + name + '.conf')
        if conf.exists():
            raise ValueError('EXISTING_TASK_NO_RESTART')
        conf.write_text('[program:' + name + ']\ncommand=' + ' '.join(command) + '\ndirectory=' + str(TREE) +
                        '\nautostart=false\nautorestart=false\nstartsecs=0\nredirect_stderr=true\nstdout_logfile=' +
                        str(out / 'execution.log') + '\nstdout_logfile_maxbytes=0\n')
        for c in (['reread'], ['update'], ['start', name]):
            subprocess.run(['supervisorctl', *c], check=True)
    else:
        with zipfile.ZipFile(str(out) + '.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in out.rglob('*'):
                if path.is_file() and path.suffix not in ('.tmp', '.log'):
                    archive.write(path, path.relative_to(out))
        subprocess.run(['supervisorctl', 'status', name])

"""Finite contextual control on the complete frozen suite."""
import argparse
import json
from pathlib import Path
import subprocess
import zipfile

TREE = Path('/workspace/guardian/repos/semantic-hybrid-v4-20261004')
OUT = Path('/workspace/guardian/results/semantic-hybrid-v4-gemma-context-20261004')
PYTHON = '/workspace/guardian/modular_venv/bin/python'
SCRIPT = '/tmp/guardian_v4_gemma_context.py'

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('phase', choices=['prepare', 'start', 'snapshot'])
    args = p.parse_args()
    if args.phase == 'prepare':
        rows = json.loads(Path('/workspace/guardian/results/semantic-hybrid-v4-gemma-contract-20261004/predictions_A0_A2.json').read_text())
        direct = [r for r in rows if r['arm'] == 'A0']
        if len(direct) != 2 or any(r['failure'] for r in direct):
            raise ValueError('CONTEXTUAL_CAPABILITY_NOT_ESTABLISHED')
        subprocess.run([PYTHON, SCRIPT, 'prepare', '--out', str(OUT)], check=True)
    elif args.phase == 'start':
        name = 'guardian_v4_gemma_context'
        conf = Path('/etc/supervisor/conf.d/' + name + '.conf')
        if conf.exists():
            raise ValueError('EXISTING_TASK_NO_RETRY')
        conf.write_text('[program:' + name + ']\ncommand=' + PYTHON + ' ' + SCRIPT + ' run --out ' + str(OUT) +
                        '\ndirectory=' + str(TREE) + '\nautostart=false\nautorestart=false\nstartsecs=0\nredirect_stderr=true\nstdout_logfile=' +
                        str(OUT / 'execution.log') + '\nstdout_logfile_maxbytes=0\n')
        for c in (['reread'], ['update'], ['start', name]):
            subprocess.run(['supervisorctl', *c], check=True)
    else:
        with zipfile.ZipFile(str(OUT) + '.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in OUT.rglob('*'):
                if path.is_file() and path.suffix not in ('.tmp', '.log'):
                    archive.write(path, path.relative_to(OUT))
        subprocess.run(['supervisorctl', 'status', 'guardian_v4_gemma_context'])

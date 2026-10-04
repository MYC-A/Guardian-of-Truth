"""Bounded capability gate and exact successful-cache continuation."""
import argparse
from pathlib import Path
import subprocess
import zipfile

TREE = Path('/workspace/guardian/repos/semantic-hybrid-v4-20261004')
OUT = Path('/workspace/guardian/results/semantic-hybrid-v4-gemma-contract-20261004')
PYTHON = '/workspace/guardian/modular_venv/bin/python'
SCRIPT = '/tmp/guardian_v4_gemma_contract.py'

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('phase', choices=['prepare', 'smoke', 'continue', 'snapshot'])
    args = p.parse_args()
    if args.phase == 'prepare':
        subprocess.run([PYTHON, SCRIPT, 'prepare', '--out', str(OUT)], check=True)
    elif args.phase in ('smoke', 'continue'):
        if args.phase == 'continue':
            import json
            rows = json.loads((OUT / 'predictions_A0_A2.json').read_text())
            if len(rows) != 4 or sum(r['failure'] is None for r in rows) < 3:
                raise ValueError('PROVIDER_CONTRACT_GATE_FAILED_NO_MORE_HTTP')
        name = 'guardian_v4_gemma_contract_' + args.phase
        conf = Path('/etc/supervisor/conf.d/' + name + '.conf')
        if conf.exists():
            raise ValueError('EXISTING_TASK_NO_RESTART')
        command = PYTHON + ' ' + SCRIPT + ' run --out ' + str(OUT)
        if args.phase == 'smoke':
            command += ' --limit 2'
        conf.write_text('[program:' + name + ']\ncommand=' + command + '\ndirectory=' + str(TREE) +
                        '\nautostart=false\nautorestart=false\nstartsecs=0\nredirect_stderr=true\nstdout_logfile=' +
                        str(OUT / 'execution.log') + '\nstdout_logfile_maxbytes=0\n')
        for c in (['reread'], ['update'], ['start', name]):
            subprocess.run(['supervisorctl', *c], check=True)
    else:
        with zipfile.ZipFile(str(OUT) + '.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in OUT.rglob('*'):
                if path.is_file() and path.suffix not in ('.tmp', '.log'):
                    archive.write(path, path.relative_to(OUT))
        for name in ('smoke', 'continue'):
            subprocess.run(['supervisorctl', 'status', 'guardian_v4_gemma_contract_' + name])

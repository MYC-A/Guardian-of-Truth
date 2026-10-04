"""Seal/start a bounded second-model control without changing primary source."""
from pathlib import Path
import argparse
import subprocess
import sys
import zipfile

TREE = Path('/workspace/guardian/repos/semantic-hybrid-v4-20261004')
OUT = Path('/workspace/guardian/results/semantic-hybrid-v4-gemma-20261004')
PYTHON = '/workspace/guardian/modular_venv/bin/python'
sys.path.insert(0, str(TREE / 'experiments/research_v3'))
from pilot import digest, read, write

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('phase', choices=['seal', 'start', 'snapshot'])
    args = p.parse_args()
    if args.phase == 'seal':
        if (OUT / 'ledger.json').exists():
            raise ValueError('NO_POST_INFERENCE_PROTOCOL_EDIT')
        protocol = read(OUT / 'protocol.json')
        protocol.pop('protocol_sha256')
        protocol['arms'] = ['A0', 'A2', 'A3']
        protocol['limits'] = {'http': 140, 'tokens': 350000}
        protocol['comparison_note'] = 'Second-model replication of frozen arms; no second A1 inference.'
        protocol['protocol_sha256'] = digest(protocol)
        write(OUT / 'protocol.json', protocol)
        print(protocol['protocol_sha256'])
    elif args.phase == 'start':
        conf = Path('/etc/supervisor/conf.d/guardian_v4_gemma.conf')
        if conf.exists():
            raise ValueError('EXISTING_MANAGED_TASK_NO_RETRY')
        conf.write_text('[program:guardian_v4_gemma]\ncommand=' + PYTHON + ' ' +
                        str(TREE / 'experiments/research_v3/pilot.py') + ' run --out ' + str(OUT) +
                        ' --arms A0 A2 A3\ndirectory=' + str(TREE) +
                        '\nautostart=false\nautorestart=false\nstartsecs=0\nredirect_stderr=true\nstdout_logfile=' +
                        str(OUT / 'execution.log') + '\nstdout_logfile_maxbytes=0\n')
        for command in (['reread'], ['update'], ['start', 'guardian_v4_gemma']):
            subprocess.run(['supervisorctl', *command], check=True)
    else:
        with zipfile.ZipFile(str(OUT) + '.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in OUT.rglob('*'):
                if path.is_file() and path.suffix not in ('.tmp', '.log'):
                    archive.write(path, path.relative_to(OUT))
        print('SNAPSHOT', str(OUT) + '.zip')
        subprocess.run(['supervisorctl', 'status', 'guardian_v4_gemma'])

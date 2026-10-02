"""Prepare own environment, startup-check interfaces, launch durable jobs."""
import json
from pathlib import Path
import subprocess
import sys

BASE = Path('/workspace/guardian')
CHECKOUT = BASE / 'repos/modular-step2-4-worktree'
PYTHON = BASE / 'modular_venv/bin/python'
OUT = BASE / 'results/modular_steps_20261002'


def launch(script, name):
    log = (OUT / (name + '_launcher.log')).open('a')
    p = subprocess.Popen([str(PYTHON), '-u', str(CHECKOUT / 'experiments/searh_23/modular_steps_20261002' / script)],
                         cwd=CHECKOUT, stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    (OUT / (name + '.pid')).write_text(str(p.pid) + '\n')
    print(json.dumps({'job': name, 'pid': p.pid}))


if __name__ == '__main__':
    own_site = subprocess.check_output([str(PYTHON), '-c', 'import sysconfig; print(sysconfig.get_path("purelib"))'], text=True).strip()
    existing_site = subprocess.check_output([str(BASE / 'venv/bin/python'), '-c', 'import sysconfig; print(sysconfig.get_path("purelib"))'], text=True).strip()
    Path(own_site, 'guardian_existing_environment.pth').write_text(existing_site + '\n')
    subprocess.run([str(PYTHON), '-c', 'import openai, torch, transformers, lxml, nltk; print("existing dependencies reusable")'], check=True)
    sys.path.insert(0, str(CHECKOUT / 'experiments/searh_23/modular_steps_20261002'))
    # Import/model prompt smoke only; no inference.
    r = subprocess.run([str(PYTHON), '-c',
        'import sys; sys.path.insert(0,"experiments/searh_23/modular_steps_20261002"); from translator_pilot import messages,IDS; from common import load_input; assert len(messages(load_input(ids=IDS)[0])[0])==2; print("translator interfaces valid")'], cwd=CHECKOUT)
    if r.returncode != 0:
        raise SystemExit(r.returncode)
    launch('run_control.py', 'control_dev')
    launch('remote_models.py', 'model_setup')
    launch('translator_pilot.py', 'translator_pilot')

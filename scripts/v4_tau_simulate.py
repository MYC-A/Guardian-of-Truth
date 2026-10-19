"""Reuse bounded official runner, excluding input-overlapping/previous source tasks."""
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ['PYTHON_DOTENV_DISABLED']='1'
BASE=Path('/workspace/guardian-lab-20261018/v3-20261019')
os.environ['TAU2_DATA_DIR']=str(BASE/'tau2-source/data')


def main():
    import importlib
    run=importlib.import_module('tau2.run')
    preflight=Path('/workspace/guardian-lab-20261018/v4-20261019/task-preflight-v1/DONE.json')
    replay=preflight.parents[1]/'reference-all-v1/DONE.json'
    clean=json.loads(preflight.read_text()); reference=json.loads(replay.read_text())
    native_complete={(r['domain'],r['task_id']) for r in reference['task_index'] if r['complete']}
    allowed={d:{r['task_id'] for r in v['allowed'] if not r['previously_simulated'] and
                (d,r['task_id']) in native_complete} for d,v in clean['domains'].items()}
    previous_v4=set()
    for path in preflight.parents[1].glob('natural-*/START.json'):
        for r in json.loads(path.read_bytes())['jobs']:
            # Reuse task/seed across models, but do not rerun a pilot within the same model.
            if ('--config-name' in sys.argv and json.loads(path.read_bytes()).get('config_name')==
                    sys.argv[sys.argv.index('--config-name')+1]):
                previous_v4.add((r['domain'],r['task_id']))
    original=run.get_tasks
    def filtered(domain):
        return [t for t in original(domain) if t.id in allowed[domain] and (domain,t.id) not in previous_v4]
    run.get_tasks=filtered
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from v3_tau_simulate import main as bounded
    bounded()
    out=Path(sys.argv[sys.argv.index('--out')+1])
    (out/'V4_FILTER.json').write_text(json.dumps(dict(
        preflight_sha256=hashlib.sha256(preflight.read_bytes()).hexdigest(),
        native_reference_sha256=hashlib.sha256(replay.read_bytes()).hexdigest(),
        wrapper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        allowed_before_new_pilot={d:len(v) for d,v in allowed.items()},
        protected_filter_is_input_only=True,full_trajectory_decontamination_still_required=True,
        no_automatic_turn_labels=True),indent=2)+'\n')


if __name__=='__main__':main()

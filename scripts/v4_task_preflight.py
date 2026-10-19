"""Input-only identity exclusion before spending GPU on natural source tasks."""
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import sys

BASE=Path('/workspace/guardian-lab-20261018')
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['TAU2_DATA_DIR']=str(BASE/'v3-20261019/tau2-source/data')
PATTERN=re.compile(r'(?i)["\x27]?(user_id|customer_id|order_id|reservation_id|booking_id|line_id|account_id|payment_id|device_id|resource_id)["\x27]?\s*[:=]\s*["\x27]?([a-zA-Z0-9_#-]{4,})')


def ids(text):return {(m.group(1).casefold(),m.group(2)) for m in PATTERN.finditer(text)}


def main():
    from tau2.run import get_tasks
    csv.field_size_limit(2**31-1)
    out=BASE/'v4-20261019/task-preflight-v1';out.mkdir(exist_ok=False)
    protected=set(); sources={}
    for name in ('regression_seen','compli_dev','compli_eval'):
        path=BASE/'data/guardian-judge-eval-data-v1'/name/'inputs.csv'
        with path.open(newline='') as f:
            for row in csv.DictReader(f):protected.update(ids(row['prompt']+'\0'+row['response']))
        sources[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('dev','holdout','stress'):
        path=BASE/'v3-20261019/hours-frozen-v2'/(name+'_inputs.jsonl')
        for line in path.read_bytes().splitlines():
            row=json.loads(line);protected.update(ids(row['prompt']+'\0'+row['response']))
        sources[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    previous={}
    for name in ('tau4b-v2','tau8b-v1'):
        rows=json.loads((BASE/'v3-20261019'/name/'START.json').read_text())['jobs']
        for row in rows:previous.setdefault(row['domain'],set()).add(row['task_id'])
    domains={}
    for domain in ('airline','retail','telecom'):
        allowed=[];excluded=[]
        tasks=get_tasks(domain)
        for task in tasks:
            # Hidden task metadata is used only for conservative exclusion;
            # it is never passed to the judge/agent as policy or trajectory.
            overlap=ids(task.model_dump_json())&protected
            if overlap:excluded.append(dict(task_id=task.id,overlap=sorted(overlap)))
            else:allowed.append(dict(task_id=task.id,previously_simulated=task.id in previous.get(domain,set())))
        domains[domain]=dict(total=len(tasks),allowed=allowed,excluded=excluded)
    report=dict(complete=True,protected_entity_pairs=len(protected),protected_sources_sha256=sources,
                original_entity_exclusion_not_relaxed=True,domains=domains)
    (out/'DONE.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:dict(total=v['total'],allowed=len(v['allowed']),excluded=len(v['excluded'])) for k,v in domains.items()}),flush=True)


if __name__=='__main__':main()

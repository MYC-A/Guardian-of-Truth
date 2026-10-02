"""Pin/deploy/validate the source-ID service, optionally launch a finite job."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def command(args):return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT).strip()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('revision');parser.add_argument('--run',action='store_true')
    parser.add_argument('--cases',type=int,default=1);parser.add_argument('--total-token-cap',type=int,default=1200000)
    parser.add_argument('--total-attempt-cap',type=int,default=350);parser.add_argument('--approval-receipt',type=Path)
    args=parser.parse_args();revision=args.revision
    if not re.fullmatch('[0-9a-f]{8,40}',revision):raise ValueError('pinned SHA required')
    if not 1<=args.cases<=46:raise ValueError('finite case count required')
    base=Path('/workspace/guardian');repo=base/'repos/Guardian-of-Truth'
    checkout=base/('repos/source-search-'+revision);python=str(base/'modular_venv/bin/python')
    names=('guardian_research','guardian_modular_20261002','guardian_source_search_376f5d14')
    old={n:command(['supervisorctl','pid',n]) for n in names}
    command(['git','-C',str(repo),'fetch','origin','research/source-search-20261002'])
    if not checkout.exists():
        command(['git','-C',str(repo),'worktree','add','--detach','--no-checkout',str(checkout),revision])
        command(['git','-C',str(checkout),'sparse-checkout','set','service','src',
            'experiments/searh_23/three_architectures','experiments/searh_23/hybrid_service_v1',
            'experiments/searh_23/source_search_20261002','outputs/searh_23/source_search_20261002'])
        command(['git','-C',str(checkout),'checkout',revision])
    sha=command(['git','-C',str(checkout),'rev-parse','HEAD'])
    if not sha.startswith(revision):raise ValueError('SHA mismatch')
    tests={}
    for test in ('test_source_search.py','test_move_scope.py','test_id_investigation.py'):
        tests[test]=command([python,str(checkout/'experiments/searh_23/source_search_20261002'/test)])
    frozen=json.loads(command([python,str(checkout/'experiments/searh_23/source_search_20261002/compare_source_ids.py')]))
    acceptance=json.loads(command([python,str(checkout/'experiments/searh_23/source_search_20261002/acceptance_ids.py')]))
    receipt={'revision':sha,'frozen':frozen,'mechanical_acceptance':acceptance,'tests':tests,
        'requested_cases':args.cases,'inference_started':False,'old_pids_before':old,
        'total_token_cap':args.total_token_cap,'total_attempt_cap':args.total_attempt_cap}
    if args.run:
        phase=base/'results/source-search-api-phase-20261002'
        if (phase/'breaker.json').exists():raise ValueError('provider breaker is open; no automatic resume')
        if args.total_token_cap>1200000 or args.total_attempt_cap>350:
            if not args.approval_receipt or not args.approval_receipt.exists():raise ValueError('approval receipt required')
            approval=json.loads(args.approval_receipt.read_text())
            if approval.get('total_tokens')!=args.total_token_cap or approval.get('total_attempts')!=args.total_attempt_cap:
                raise ValueError('cap mismatch with approval')
            receipt['budget_authorization']=approval
        name='guardian_source_ids_'+revision[:8]+'_'+str(args.cases)
        config=Path('/etc/supervisor/conf.d')/(name+'.conf')
        if config.exists():raise ValueError('job already exists; inspect the handle instead of restarting')
        out=base/('results/source-ids-'+revision+'-'+str(args.cases));out.mkdir(parents=True,exist_ok=True)
        cmd=[python,'experiments/searh_23/source_search_20261002/compare_source_ids.py','--run',
             '--cases',str(args.cases),'--total-token-cap',str(args.total_token_cap),
             '--total-attempt-cap',str(args.total_attempt_cap)]
        if args.approval_receipt:cmd+=['--approval-receipt',str(args.approval_receipt)]
        import shlex
        config.write_text(f'''[program:{name}]
command={shlex.join(cmd)}
directory={checkout}
autostart=true
autorestart=false
startsecs=0
stopasgroup=true
killasgroup=true
stdout_logfile={out}/run.log
stderr_logfile={out}/run.err.log
''')
        command(['supervisorctl','reread']);command(['supervisorctl','update',name])
        receipt.update(inference_started=True,program=name,status=command(['supervisorctl','status',name]))
    else:
        out=base/('results/source-ids-'+revision+'-prepare');out.mkdir(parents=True,exist_ok=True)
    after={n:command(['supervisorctl','pid',n]) for n in names}
    if old!=after:raise ValueError('existing service PID changed')
    receipt['old_pids_after']=after
    (out/'launch.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps({k:v for k,v in receipt.items() if k!='tests'}))


if __name__=='__main__':main()

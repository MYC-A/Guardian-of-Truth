"""CPU-only pinned tau2 reference execution and natural-trajectory inventory; not turn gold."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import time

os.environ['PYTHON_DOTENV_DISABLED'] = '1'
BASE = Path('/workspace/guardian-lab-20261018/v3-20261019')
os.environ['TAU2_DATA_DIR'] = str(BASE/'tau2-source/data')
PIN = '96a3ef92329baf908ffe9dfe188cea34e8701d2a'


def primitive(value):
    if hasattr(value, 'model_dump'):
        return value.model_dump(mode='json')
    return value


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def changes(before, after, path='$'):
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        out = []
        for key in sorted(before.keys() | after.keys()):
            if key not in before or key not in after:
                out.append(dict(path=path+'.'+key, before=before.get(key), after=after.get(key)))
            else:
                out.extend(changes(before[key], after[key], path+'.'+key))
        return out
    return [dict(path=path, before=before, after=after)]


def state(env):
    return dict(agent=primitive(env.tools.db),
                user=primitive(env.user_tools.db) if env.user_tools is not None else None)


def initial(env, task):
    setup = task.initial_state
    if setup is not None:
        env.set_state(initialization_data=setup.initialization_data,
                      initialization_actions=setup.initialization_actions,
                      message_history=setup.message_history or [], strict=True)


def main():
    p = argparse.ArgumentParser(); p.add_argument('--out', type=Path, required=True)
    p.add_argument('--limit-per-domain', type=int, default=0)
    args = p.parse_args(); args.out.mkdir(exist_ok=False)
    from tau2.run import get_tasks
    from tau2.runner.build import build_environment
    from loguru import logger
    logger.remove()
    began = time.time(); counts = Counter(); catalog = {}; tasks_index = []
    (args.out/'START.json').write_text(json.dumps(dict(source_revision=PIN,
        protocol='V4_DATA_PREPARATION_PROTOCOL.md', script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        started_unix=began, gpu_used=False, references_are_not_turn_labels=True), indent=2))
    for domain in ('airline','retail','telecom'):
        env = build_environment(domain)
        catalog[domain] = dict(policy=env.get_policy(), tools=[t.openai_schema for t in env.get_tools()])
        tasks = sorted(get_tasks(domain), key=lambda t: hashlib.sha256((domain+':'+t.id).encode()).hexdigest())
        if args.limit_per_domain:
            tasks = tasks[:args.limit_per_domain]
        for task in tasks:
            record = dict(domain=domain,task_id=task.id,source_revision=PIN,
                          task=task.model_dump(mode='json'),steps=[],turn_labels_assigned=False)
            key = hashlib.sha256((domain+':'+task.id).encode()).hexdigest()[:20]
            try:
                env = build_environment(domain); initial(env,task)
                criteria = task.evaluation_criteria
                actions = criteria.actions if criteria and criteria.actions else []
                record['initial_db_hash'] = env.get_db_hash()
                for ordinal, action in enumerate(actions):
                    before = state(env)
                    step = dict(ordinal=ordinal, action=action.model_dump(mode='json'),
                                before_sha256=sha(before))
                    try:
                        value = env.make_tool_call(action.name,requestor=action.requestor,**action.arguments)
                        env.sync_tools(); after = state(env)
                        step.update(complete=True,result=primitive(value),after_sha256=sha(after),
                                    db_changes=changes(before,after))
                        counts[domain+':reference_calls_completed'] += 1
                    except Exception as exc:
                        step.update(complete=False,error_type=type(exc).__name__,error=str(exc))
                    record['steps'].append(step)
                    if not step['complete']:
                        break
                record['reference_calls_executed'] = len(record['steps'])
                record['complete'] = len(record['steps']) == len(actions) and all(s['complete'] for s in record['steps'])
                record['expected_reference_calls'] = len(actions)
            except Exception as exc:
                record.update(complete=False,error_type=type(exc).__name__,error=str(exc))
            counts[domain+(':tasks_completed' if record['complete'] else ':tasks_failed')] += 1
            dest = args.out/(domain+'-'+key+'.json')
            dest.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str)+'\n')
            tasks_index.append(dict(domain=domain,task_id=task.id,path=dest.name,complete=record['complete'],
                                    sha256=hashlib.sha256(dest.read_bytes()).hexdigest()))
            if len(tasks_index)%20==0:
                print(json.dumps(dict(tasks=len(tasks_index),seconds=time.time()-began,counts=dict(counts))),flush=True)
    (args.out/'CATALOG.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n')
    natural = []
    for name in ('tau4b-v2','tau8b-v1'):
        for path in sorted((BASE/name).glob('*.json')):
            if path.stem in {'START','DONE','CATALOG'}:
                continue
            record = json.loads(path.read_bytes()); sim = record.get('simulation',{})
            messages = sim.get('messages',[]); assistant = [m for m in messages if m.get('role')=='assistant']
            natural.append(dict(config=name,source_file=str(path),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                complete=record.get('complete'),domain=record['domain'],task_id=record['task_id'],seed=record['seed'],
                assistant_turns=len(assistant),assistant_tool_calls=sum(len(m.get('tool_calls') or []) for m in assistant),
                text_and_call_turns=sum(bool(m.get('content')) and bool(m.get('tool_calls')) for m in assistant),
                total_messages=len(messages),turn_labels_assigned=False,
                independent_task_key=record['domain']+':'+record['task_id']))
    final = dict(complete=True,seconds=time.time()-began,counts=dict(counts),task_index=tasks_index,
        natural_trajectories=natural,natural_turns_candidate=sum(r['assistant_turns'] for r in natural),
        natural_unique_task_components=len({r['independent_task_key'] for r in natural}),
        source_revision=PIN,human_reviewed=False,reference_execution_is_not_policy_admissibility=True)
    (args.out/'DONE.json').write_text(json.dumps(final,indent=2)+'\n')
    print(json.dumps({k:v for k,v in final.items() if k not in {'task_index','natural_trajectories'}}),flush=True)


if __name__=='__main__':main()

"""CPU parser inventory; run old/new source roots in separate processes.

Only already explored regression labels are read. compli_eval is input-only.
No inference, relabeling or modification of a frozen training run.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys


def read(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def main():
    p=argparse.ArgumentParser()
    for name in ('src','protected','frozen','out'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();sys.path.insert(0,str(a.src.resolve()))
    from guardian_truth.judge.mechanical import analyze
    from guardian_truth.transcript import parse_document,parse_system
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from v4_data import judge_input
    csv.field_size_limit(2**31-1)
    a.out.mkdir(parents=True,exist_ok=False)
    summaries={}
    for name in ('regression_seen','compli_dev','compli_eval','train','dev','holdout'):
        if name in ('train','dev','holdout'):
            gold=read(a.frozen/(name+'.jsonl'))
            rows=[judge_input(g) for g in gold] if name=='train' else read(a.frozen/(name+'_inputs.jsonl'))
            sources=[a.frozen/(name+'.jsonl')]
        else:
            file=a.protected/name/'inputs.csv'
            with file.open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
            gold=None if name=='compli_eval' else read(a.protected/name/'labels.jsonl')
            sources=[file]
        assert gold is None or len(rows)==len(gold)
        counts=Counter();records=[]
        for i,r in enumerate(rows):
            g=None if gold is None else gold[i]
            assert g is None or g['id']==r['id']
            prompt=parse_document(r['prompt']);turn=parse_document(r['response'],'response');system=parse_system(prompt)
            original=analyze(r['prompt'],r['response']);shape=analyze(r['prompt'],r['response'],bounded_turn_shape=True)
            rec=dict(id=r['id'],label=None if g is None else g['label'],domain=None if g is None else g.get('domain'),
                catalog_present=system.catalog.present,catalog_complete=system.catalog.complete,
                catalog_issues=system.catalog.issues,tools=len(system.catalog.tools),
                schemas_understood=sum(t.understood for t in system.catalog.tools.values()),
                prompt_diagnostics=prompt.diagnostics,response_diagnostics=turn.diagnostics,
                prompt_events=len(prompt.events),response_events=len(turn.events),
                response_calls=len(turn.calls(owner='assistant')),hard=original.hard,shape_hard=shape.hard,
                unpaired_results=sum(e.pair is None for e in prompt.results()),
                result_role_owner_mismatch=sum(e.owner!=e.role for e in prompt.results()),
                error_features={k:v for k,v in shape.features.items()
                    if k in {'date_gate_error','bounded_turn_shape_error'} and v})
            records.append(rec);counts['rows']+=1
            for key in ('catalog_present','catalog_complete','unpaired_results','result_role_owner_mismatch'):
                counts[key]+=int(bool(rec[key]))
            for key in ('hard','shape_hard','prompt_diagnostics','response_diagnostics','error_features'):
                counts[key+'_rows']+=int(bool(rec[key]))
            if g is not None and g['label']==0:
                counts['negative_rows']+=1
                counts['hard_on_gold0']+=int(bool(original.hard))
                counts['shape_hard_on_gold0']+=int(bool(shape.hard))
        (a.out/(name+'.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=True)+'\n' for r in records),encoding='utf-8')
        summaries[name]=dict(counts=counts,input_sha256={str(s):hashlib.sha256(s.read_bytes()).hexdigest() for s in sources},
            labels_used=gold is not None)
    (a.out/'SUMMARY.json').write_text(json.dumps(summaries,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summaries))


if __name__=='__main__':main()

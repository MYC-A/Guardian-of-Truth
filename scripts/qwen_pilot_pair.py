"""Compare complete pilot exports after independent integrity/scoring checks."""
import argparse
import json
from pathlib import Path
import zipfile

from qwen_pilot_summarize import summarize


def read(bundle, arm):
    with zipfile.ZipFile(bundle) as z:
        prefix = arm+'/rep1/'
        rows = [json.loads(line) for line in z.read(prefix+'receipts/traces.jsonl').decode('utf-8').splitlines() if line.strip()]
        return {r['id']:r for r in rows}, json.loads(z.read('freeze.json'))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--baseline-arm', required=True)
    p.add_argument('--candidate-arm', required=True)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args=p.parse_args()
    first=summarize(args.baseline,args.input,args.baseline_arm)
    second=summarize(args.candidate,args.input,args.candidate_arm)
    a, freeze_a=read(args.baseline,args.baseline_arm)
    b, freeze_b=read(args.candidate,args.candidate_arm)
    if freeze_a != freeze_b or set(a) != set(b):raise ValueError('UNMATCHED_PHASE')
    def delivery(rows):
        steps=[s for r in rows.values() for s in r.get('pre_steps',[]) if s.get('tag')=='pre_blind']
        return {'proposals':len(steps),'parsed_ok':sum(s.get('parsed_ok') is True for s in steps),
                'delivered':sum(s.get('injected') is True for s in steps)}
    result={'scope':'One full matched ordered feasibility repetition; not acceptance',
        'baseline':first,'candidate':second,'freeze':freeze_a,
        'wall_reduction_seconds':first['cli_seconds']-second['cli_seconds'],
        'wall_reduction_percent':100*(1-second['cli_seconds']/first['cli_seconds']),
        'pre_delivery':{args.baseline_arm:delivery(a),args.candidate_arm:delivery(b)},
        'binary_flips':[{'id':i,'before':a[i]['binary'],'after':b[i]['binary'],
                        'before_owner':a[i].get('owner'),'after_owner':b[i].get('owner')}
                       for i in sorted(a) if a[i]['binary']!=b[i]['binary']],
        'candidate_recoveries':[{'id':i,'binary':r['binary'],'recovery':r['output_recovery'],
            'primary_admission':(r.get('rec') or {}).get('A_adm2')}
            for i,r in sorted(b.items()) if r.get('output_recovery')]}
    with args.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,ensure_ascii=False)
    print(json.dumps({'wall_reduction_percent':result['wall_reduction_percent'],
                      'binary_flips':result['binary_flips'],'pre_delivery':result['pre_delivery']}))

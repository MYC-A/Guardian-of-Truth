"""Gold-reading analysis, separate from the label-blind PolicyGuard runner."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.analyze_judge_dependencies_20261018 import metrics,rank_metrics,ranks
from scripts.analyze_judge_gpu_run_20261018 import paired_ci
from guardian_truth.judge.decision import decide


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--labels',type=Path,required=True)
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--subset-data',type=Path)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    start=json.loads((args.run/'START.json').read_bytes())
    done=json.loads((args.run/'DONE.json').read_bytes())
    assert done['complete'] and done['rows']==start['rows']
    assert hashlib.sha256(args.inputs.read_bytes()).hexdigest()==start['input_file_sha256']
    records=[json.loads(l) for l in (args.run/'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    gold=[json.loads(l) for l in args.labels.read_text(encoding='utf-8').splitlines()]
    assert len(records)==len(gold)==done['rows']
    if start['mode']=='native':
        inputs=[json.loads(l) for l in args.inputs.read_text(encoding='utf-8').splitlines()]
        hashes=[hashlib.sha256(r['policy_and_trajectory'].encode()).hexdigest() for r in inputs]
        y=[int(g['label']=='violation') for g in gold]
        assert all(g['label'] in ('violation','no_violation') for g in gold)
    else:
        csv.field_size_limit(2**31-1)
        with args.inputs.open(encoding='utf-8',newline='') as f: inputs=list(csv.DictReader(f))
        hashes=[hashlib.sha256((r['prompt']+'\0'+r['response']).encode()).hexdigest() for r in inputs]
        y=[g['label'] for g in gold]
        assert set(y)=={0,1}
    for i,(r,g,h,inp) in enumerate(zip(records,gold,hashes,inputs)):
        assert r['id']==g['id']==inp['id'] and r['position']==g['position']==i
        assert r['source_sha256']==h
        if start['mode']=='transfer':
            pair=json.dumps([inp['prompt'],inp['response']],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
            assert hashlib.sha256(pair).hexdigest()==g['source_pair_sha256']
    subset=None
    if args.subset_data:
        assert start['mode']=='transfer' and args.out
        sg=[json.loads(l) for l in (args.subset_data/'labels.jsonl').read_text(encoding='utf-8').splitlines()]
        with (args.subset_data/'inputs.csv').open(encoding='utf-8',newline='') as f: si=list(csv.DictReader(f))
        assert len(sg)==len(si) and len({r['id'] for r in records})==len(records)
        indices={r['id']:i for i,r in enumerate(records)}
        selected=[]
        for j,(g,inp) in enumerate(zip(sg,si)):
            assert g['id']==inp['id'] and g['position']==j
            i=indices[g['id']]
            assert g['label']==gold[i]['label'] and g['source_pair_sha256']==gold[i]['source_pair_sha256']
            pair=json.dumps([inp['prompt'],inp['response']],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
            assert hashlib.sha256(pair).hexdigest()==g['source_pair_sha256']
            selected.append(i)
        subset=dict(name=args.subset_data.name,parent_rows=len(records),source_positions=selected,
                    new_model_calls=0,independent_samples_added=0,
                    note='Exact source-pair subset of the parent run; parent context/time apply.')
        records=[records[i] for i in selected];gold=sg;y=[g['label'] for g in sg]
    strict=[i for i,r in enumerate(records) if r['strict_label'] is not None]
    result=dict(mode=start['mode'],rows=len(records),positive=sum(y),strict_coverage=len(strict),
        strict_subset_metrics=metrics([y[i] for i in strict],[records[i]['strict_label'] for i in strict]),
        author_permissive_parser_metrics=metrics(y,[r['author_substring_label'] for r in records]),
        output_counts=dict(Counter(r['raw_output'] for r in records)),
        unknown_outputs=dict(Counter(r['raw_output'] for r in records if r['strict_label'] is None)),
        finish_reasons=dict(Counter(r['finish_reason'] for r in records)),runtime=done,
        conclusion='EXPLORATORY_NATIVE_TRAJECTORY_OR_SEEN_TRANSFER_NOT_PLATFORM_GAIN')
    if subset: result['derived_subset']=subset
    if all('score' in r for r in records):
        scores=[r['score'] for r in records]
        result['ranking']=rank_metrics(y,scores)
        result['pure_model_quota']={str(rate):metrics(y,decide(len(y),set(),dict(enumerate(scores)),rate)) for rate in (.3,.4)}
        if args.baseline:
            with args.baseline.open(encoding='utf-8',newline='') as f: base=list(csv.DictReader(f))
            assert len(base)==len(records)
            assert all(b['id']==r['id'] and int(b['label'])==label for b,r,label in zip(base,records,y))
            hard={i for i,b in enumerate(base) if b['hard']}
            candidate=decide(len(y),hard,dict(enumerate(scores)),.4)
            prior=decide(len(y),hard,{i:float(b['final_score']) for i,b in enumerate(base)},.4)
            result['paired_vs_qwen_final_at_40']=dict(candidate=metrics(y,candidate),reference=metrics(y,prior),
                grouped_ci=paired_ci(y,prior,candidate,[g['group'] for g in gold]),
                fixed=sum(a!=label and b==label for a,b,label in zip(prior,candidate,y)),
                broken=sum(a==label and b!=label for a,b,label in zip(prior,candidate,y)),
                tp_overlap=sum(label and a and b for label,a,b in zip(y,prior,candidate)),
                candidate_unique_tp=sum(label and not a and b for label,a,b in zip(y,prior,candidate)),
                reference_unique_tp=sum(label and a and not b for label,a,b in zip(y,prior,candidate)))
            equal=[(a+b)/2 for a,b in zip(ranks(scores),ranks([float(b['final_score']) for b in base]))]
            result['fixed_equal_rank_mean']={str(rate):metrics(y,decide(len(y),hard,dict(enumerate(equal)),rate)) for rate in (.3,.4)}
            ensemble=decide(len(y),hard,dict(enumerate(equal)),.4)
            result['fixed_equal_rank_mean']['paired_at_40']=dict(
                grouped_ci=paired_ci(y,prior,ensemble,[g['group'] for g in gold]),
                fixed=sum(a!=label and b==label for a,b,label in zip(prior,ensemble,y)),
                broken=sum(a==label and b!=label for a,b,label in zip(prior,ensemble,y)))
        if any(g.get('domain') in ('airlines','healthcare','insurance') for g in gold):
            result['domains']={}
            for name,domains in [('airlines_healthcare',{'airlines','healthcare'}),('insurance',{'insurance'})]:
                idx=[i for i,g in enumerate(gold) if g.get('domain') in domains]
                ly=[y[i] for i in idx];ls=[scores[i] for i in idx]
                result['domains'][name]=dict(rows=len(idx),positive=sum(ly),ranking=rank_metrics(ly,ls),
                    pure_model_quota={str(rate):metrics(ly,decide(len(ly),set(),dict(enumerate(ls)),rate)) for rate in (.3,.4)})
    (args.out or args.run/'ANALYSIS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('runtime','output_counts')},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()

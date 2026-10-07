"""Independent arithmetic over immutable Git blobs; no network or model calls."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess

import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--commit', required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    def blob(path):
        return subprocess.check_output(['git','show',a.commit+':'+path])
    gold_bytes = blob('valid.parquet')
    gold = {r.id:int(r.label) for r in pd.read_parquet(io.BytesIO(gold_bytes)).itertuples()}
    if len(gold) != 46 or sum(gold.values()) != 23:
        raise ValueError('UNEXPECTED_VALID46_CONTRACT')
    def records(path):
        rows = [json.loads(line) for line in blob(path).decode('utf-8').splitlines()]
        result = {r['id']:r for r in rows}
        if len(result)!=len(rows) or set(result)!=set(gold):
            raise ValueError('INVALID_EXPECTED_IDS:'+path)
        return result
    witness = records('outputs/guardian_lynx_witness_20261007/runs.jsonl')
    qwen = records('outputs/guardian_local_a100/llamacpp/qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459/runs/valid46/B2_rep1.jsonl')
    def score(values):
        counts = dict(TP=0,FP=0,FN=0,TN=0,unavailable_positive=0,unavailable_negative=0)
        for k,label in gold.items():
            value=values.get(k)
            if value is None:
                counts['unavailable_positive' if label else 'unavailable_negative']+=1
            else:
                if type(value) is not int or value not in (0,1):
                    raise ValueError('NONBINARY_DECISION')
                counts[{(1,1):'TP',(1,0):'FP',(0,1):'FN',(0,0):'TN'}[value,label]]+=1
        tp,fp,fn = (counts[x] for x in ('TP','FP','FN'))
        return dict(counts,precision=tp/(tp+fp) if tp+fp else None,
                    recall=tp/(tp+fn) if tp+fn else None,
                    conditional_f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)
    def turn(r):
        return int(r['verdict']=='FAIL') if r.get('status')=='VALID' and r.get('verdict') in ('PASS','FAIL') else None
    report = dict(commit=a.commit,gold_sha256=hashlib.sha256(gold_bytes).hexdigest(),rows=46,
                  arms={'legacy_v3':score({k:turn(r['legacy_turn']) for k,r in witness.items()}),
                        'witness_v4':score({k:turn(r['turn']) for k,r in witness.items()}),
                        'qwen_b2':score({k:r['binary'] for k,r in qwen.items()})})
    for field in ('old_check','action_check','witness_check'):
        predictions={}
        for k,r in witness.items():
            if qwen[k]['binary'] != 1:
                predictions[k]=qwen[k]['binary']
                continue
            candidates=[item for item in r['accusations'] if item['model']=='qwen']
            if len(candidates)!=1: raise ValueError('QWEN_ACCUSATION_COVERAGE')
            verdict=turn(candidates[0][field])
            predictions[k]=1-verdict if verdict is not None else None
        report['arms']['qwen_filter_'+field]=score(predictions)
    published_v4=json.loads(blob('outputs/guardian_lynx_witness_20261007/score.json'))
    published=dict(legacy_v3=published_v4['turn_old'],witness_v4=published_v4['turn_witness'],
                   qwen_b2=published_v4['qwen_base'])
    for field in ('old_check','action_check','witness_check'):
        published['qwen_filter_'+field]=published_v4['filters'][field]['raw_filter']
    for name,actual in report['arms'].items():
        for key in ('TP','FP','FN','TN','unavailable_positive','unavailable_negative','conditional_f1'):
            if actual[key] != published[name][key]:
                raise ValueError('PUBLISHED_SCORE_MISMATCH:'+name+':'+key)
    report['published_scores_match']=True
    report['question_v5']='Stopped by user; no full-set metric'
    with a.output.open('x',encoding='utf-8') as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
        f.write('\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()

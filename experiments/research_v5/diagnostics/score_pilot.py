"""Gold-reading scorer; never imported by the model runner."""
from collections import Counter
import json
from pathlib import Path
import sys
import argparse

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(Path(__file__).parent))
from binary_audit import metrics,sha
import pandas as pd


def main(out):
    records=json.loads((out/'predictions.json').read_text(encoding='utf-8'))
    protocol=json.loads((out/'protocol.json').read_text(encoding='utf-8'))
    ledger=json.loads((out/'ledger.json').read_text(encoding='utf-8'))
    original=pd.read_parquet(ROOT/'valid.parquet')
    gold=dict(zip(original.id,original.label.map(int)))
    lookup={(r['id'],r['arm']):r for r in records}
    ids=[i for i in gold if (i,'D0') in lookup]
    assert len(ids)==3 and len(lookup)==6
    source=json.loads((ROOT/'outputs/research_v5/binary_audit/valid46_case_audit.json').read_text(encoding='utf-8'))
    source={r['id']:r['source_sha256'] for r in source}
    assert all(r['source_sha256']==source[r['id']] for r in records)
    common=[i for i in ids if all(not lookup[i,a]['failure'] for a in ('D0','P3'))]
    scores={};costs={}
    for arm in ('D0','P3'):
        selected=[r for r in records if r['arm']==arm]
        pred={r['id']:r['result']['binary'] for r in selected}
        scores[arm]=dict(all_selected_cases=metrics({i:gold[i] for i in ids},pred),
                        common_admitted_pairs=metrics({i:gold[i] for i in common},{i:pred[i] for i in common}),
                        decisions=Counter(r['result']['decision'] for r in selected),
                        failures=Counter(r['failure'] for r in selected if r['failure']))
        used=[v for v in ledger.values() if v['arm']==arm]
        costs[arm]=dict(http=len(used),known_tokens=sum(v['known_tokens'] for v in used),
                       charged_tokens=sum(v['charged_tokens'] for v in used),seconds=sum(v.get('seconds',0) for v in used))
    rows=[dict(id=i,gold=gold[i],D0=lookup[i,'D0']['result']['decision'],P3=lookup[i,'P3']['result']['decision'],
               D0_failure=lookup[i,'D0']['failure'],P3_failure=lookup[i,'P3']['failure']) for i in ids]
    result=dict(data_status='PUBLIC_KNOWN_SELECTED_DEVELOPMENT_NOT_HOLDOUT',selected_n=3,common_admitted_n=len(common),
        gold_sha256=sha('valid.parquet'),unknown_binary_mapping=0,protocol_sha256=protocol['protocol_sha256'],
        rows=rows,scores=scores,costs=costs,actual_provider_models=Counter(r['provider_model'] for r in records if r['provider_model']),
        paired_correctness=dict(P3_only_correct=[i for i in common if lookup[i,'P3']['result']['binary']==gold[i] and lookup[i,'D0']['result']['binary']!=gold[i]],
                               D0_only_correct=[i for i in common if lookup[i,'D0']['result']['binary']==gold[i] and lookup[i,'P3']['result']['binary']!=gold[i]]),
        automatic_full_valid46_metric_available=False,architecture_improvement_claim=False,
        caution='Three selected cases cannot demonstrate a binary F1 gain on valid46 or generalization. Schema admission is not semantic correctness. A P3 UNKNOWN negative is abstention, not a correctness certificate.')
    (out/'diagnostic_score.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    main(p.parse_args().out)

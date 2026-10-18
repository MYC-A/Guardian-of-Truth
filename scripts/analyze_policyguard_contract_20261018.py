"""Analyze all frozen native Transformers format diagnostics; no winner fitting."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.analyze_judge_dependencies_20261018 import metrics


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--labels',type=Path,required=True)
    a=p.parse_args();gold=[json.loads(l) for l in a.labels.read_text().splitlines()]
    assert len(gold)==300 and {g['label'] for g in gold}=={'violation','no_violation'}
    y=[int(g['label']=='violation') for g in gold];result={}
    for name in ['raw_greedy4','raw_card_defaults4','raw_greedy16','chat_greedy16']:
        r=[json.loads(l) for l in (a.run/(name+'.jsonl')).read_text().splitlines()]
        assert len(r)==300 and all(x['id']==g['id'] and x['position']==g['position'] for x,g in zip(r,gold))
        ix=[i for i,x in enumerate(r) if x['strict_label'] is not None]
        result[name]=dict(author_parser=metrics(y,[x['author_substring_label'] for x in r]),
            strict_coverage=len(ix),strict_subset=metrics([y[i] for i in ix],[r[i]['strict_label'] for i in ix]),
            outputs=dict(Counter(x['raw'] for x in r)))
    check=json.loads((a.run/'FULL_LABEL_CHECK.json').read_bytes())
    check['max_abs_logprob_difference']=max(abs(r['difference']) for r in check['records'])
    result['full_label_check']=check;result['runtime']=json.loads((a.run/'DONE.json').read_bytes())
    (a.run/'ANALYSIS.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v['author_parser'] for k,v in result.items() if k not in ('full_label_check','runtime')},indent=2))


if __name__=='__main__':main()

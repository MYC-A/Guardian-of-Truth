"""Actual HTTP checks of real structural cases; zero model calls required."""
import json
from pathlib import Path
import sys
import urllib.request

from acceptance import rows
from structural_v02 import parse_case_v02


def request(path, value=None):
    body = None if value is None else json.dumps(value).encode()
    req = urllib.request.Request('http://127.0.0.1:18094'+path,data=body,
        headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as reply:
        return json.loads(reply.read())


def main():
    health, ready = request('/health'), request('/ready')
    receipts=[]
    for row in rows():
        ctx=parse_case_v02(row['id'],row['prompt'],row['response'])
        if not ctx.structural_hits:
            continue
        result=request('/v1/check',{'case_id':row['id'],'prompt':row['prompt'],'response':row['response']})
        assert result['decision']=='ERROR'
        assert result['coverage']['source_index_complete']
        assert result['source_store']['raw']=={'prompt':row['prompt'],'response':row['response']}
        assert result['usage']['calls']==0
        receipts.append({'case_id':row['id'],'decision':result['decision'],
            'source_archive':result['coverage']['source_archive'],'usage':result['usage']})
    receipt={'scope':'LIVE_HTTP_11_REAL_STRUCTURAL_CASES_NO_LLM_QUALITY_OR_COLD_PROVIDER_PROOF',
        'health':health,'ready':ready,'cases':receipts,'count':len(receipts),'actual_model_calls':0}
    Path(sys.argv[1]).write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps({'passed':len(receipts),'actual_model_calls':0,'ready':ready.get('ready')}))


if __name__=='__main__':
    main()

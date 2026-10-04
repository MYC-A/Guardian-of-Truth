"""Read-only metadata/tokenizer preflight. No model inference or retries."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'experiments/research_v3'))
import pilot

MODEL='ministral-14b-2512'
TOKENIZER_URL='https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512/resolve/d1002e707ddf4eab6f17da795287fb9d0d334aed/tokenizer.json'
TOKENIZER_SHA='286acad9b0e27fce778ac429763536accf618ccb6ed72963b6f94685e531c5c7'


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--cache',type=Path,required=True)
    a=p.parse_args()
    if (a.out/'provider_preflight.json').exists():raise ValueError('PREFLIGHT_ALREADY_EXISTS_NO_RETRY')
    a.out.mkdir(parents=True,exist_ok=True);a.cache.mkdir(parents=True,exist_ok=True)
    info=dict(inference_http=0,metadata_http=0,tokenizer_http=0,model=MODEL,tokenizer_url=TOKENIZER_URL,tokenizer_sha256=TOKENIZER_SHA)
    try:
        credential=pilot.credentials('mistral')
        if not credential:raise ValueError('CREDENTIAL_UNAVAILABLE')
        request=urllib.request.Request('https://api.mistral.ai/v1/models',headers={'Authorization':'Bearer '+credential})
        info['metadata_http']=1
        with urllib.request.build_opener(pilot.NoRedirect()).open(request,timeout=20) as r:models=json.loads(r.read())
        selected=[m for m in models['data'] if m['id']==MODEL]
        if len(selected)!=1:raise ValueError('PINNED_MODEL_UNAVAILABLE')
        info['metadata']={k:v for k,v in selected[0].items() if k in ('id','max_context_length','aliases','name','capabilities','created')}
        file=a.cache/(TOKENIZER_SHA+'.json')
        if not file.exists():
            info['tokenizer_http']=1
            with urllib.request.urlopen(TOKENIZER_URL,timeout=30) as r:data=r.read()
            if hashlib.sha256(data).hexdigest()!=TOKENIZER_SHA:raise ValueError('TOKENIZER_HASH_MISMATCH')
            file.write_bytes(data)
        if hashlib.sha256(file.read_bytes()).hexdigest()!=TOKENIZER_SHA:raise ValueError('TOKENIZER_HASH_MISMATCH')
        from tokenizers import Tokenizer
        tokenizer=Tokenizer.from_file(str(file))
        info.update(status='READY',tokenizer_file=str(file),tokenizer_test_tokens=len(tokenizer.encode('Проверка полного контекста.').ids))
    except Exception as e:
        info.update(status='BLOCKED',cause=type(e).__name__,http_status=getattr(e,'code',None))
    (a.out/'provider_preflight.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in info.items() if k not in ('tokenizer_file','metadata')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()

"""Single-attempt, source-sealed research transport with durable reservations."""
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

from experiments.research_v3.pilot import credentials,NoRedirect
from guardian_truth.parsing import decode_json
from guardian_truth.source_search.store import digest

ENDPOINT='https://api.mistral.ai/v1/chat/completions'
HTTP_LIMIT=10
TOKEN_LIMIT=60000


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    temp.replace(path)


def bound(body,tokenizer):
    return 2*len(tokenizer.encode(json.dumps(body,ensure_ascii=False,separators=(',',':'))).ids)+body['max_tokens']+1024


def valid_usage(data):
    usage=data.get('usage')
    if not isinstance(usage,dict):return None
    total=usage.get('total_tokens')
    if type(total) is not int or total<1:return None
    if 'prompt_tokens' in usage or 'completion_tokens' in usage:
        p,c=usage.get('prompt_tokens'),usage.get('completion_tokens')
        if type(p) is not int or type(c) is not int or min(p,c)<0 or p+c!=total:return None
    return total


class Client:
    def __init__(self,out,protocol,tokenizer,live):
        self.out,self.protocol,self.tokenizer,self.live=out,protocol,tokenizer,live
        self.ledger=read(out/'ledger.json') if (out/'ledger.json').exists() else {}
        self.breaker=any(v['status']!='OK' or v.get('unknown_usage',True) for v in self.ledger.values())
        self.new_http=0
        for key,item in self.ledger.items():
            if len(key)!=64 or type(item['charged_tokens']) is not int or item['charged_tokens']<0:
                raise ValueError('LEDGER_INVALID')
        if len(self.ledger)>HTTP_LIMIT or sum(v['charged_tokens'] for v in self.ledger.values())>TOKEN_LIMIT:
            raise ValueError('LEDGER_OVER_LIMIT')

    def ask(self,name,body):
        key=digest(body);reservation=bound(body,self.tokenizer)
        if reservation>self.protocol.get('context_limit',262144):
            return None,'CONTEXT_STOP'
        rawpath=self.out/'raw'/(key+'.json')
        requestpath=self.out/'requests'/(key+'.json')
        if rawpath.exists():
            if key not in self.ledger:raise ValueError('ORPHAN_RAW_RESPONSE')
            item=self.ledger[key]
            record=read(rawpath)
            if item.get('raw_sha256')!=hashlib.sha256(rawpath.read_bytes()).hexdigest():raise ValueError('RAW_CHANGED')
            if record['request_sha256']!=key or record['protocol_sha256']!=self.protocol['protocol_sha256']:
                raise ValueError('CACHE_IDENTITY_MISMATCH')
            if not requestpath.exists() or read(requestpath)['body']!=body:
                raise ValueError('REQUEST_CHANGED')
            if any(item[k]!=record[k] for k in ('status','charged_tokens','known_tokens','unknown_usage','name')):
                raise ValueError('RAW_LEDGER_MISMATCH')
            return record,None
        if key in self.ledger:return None,'PRIOR_RESERVED_NO_RETRY'
        if self.breaker:return None,'PROVIDER_BREAKER_NO_RETRY'
        if len(self.ledger)>=HTTP_LIMIT or sum(v['charged_tokens'] for v in self.ledger.values())+reservation>TOKEN_LIMIT:
            return None,'BUDGET_STOP'
        if not self.live:return None,'CACHE_MISS_OFFLINE'
        secret=credentials('mistral')
        if not secret:
            self.breaker=True
            return None,'CREDENTIAL_UNAVAILABLE'
        self.ledger[key]=dict(status='RESERVED',charged_tokens=reservation,known_tokens=0,unknown_usage=True,name=name)
        save(self.out/'ledger.json',self.ledger)
        save(requestpath,dict(body=body,request_sha256=key,protocol_sha256=self.protocol['protocol_sha256'],reservation_tokens=reservation))
        record=dict(name=name,request_sha256=key,protocol_sha256=self.protocol['protocol_sha256'])
        started=time.monotonic();self.new_http+=1
        try:
            request=urllib.request.Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False,separators=(',',':')).encode(),
                       headers={'Content-Type':'application/json','Authorization':'Bearer '+secret})
            with urllib.request.build_opener(NoRedirect()).open(request,timeout=120) as response:
                data,valid=decode_json(response.read().decode())
                if not valid or not isinstance(data,dict):raise ValueError('PROVIDER_JSON_INVALID')
            record.update(status='OK',provider_response=data)
        except urllib.error.HTTPError as exc:
            record.update(status='HTTP_ERROR',http_status=exc.code);self.breaker=True
        except Exception as exc:
            record.update(status='TRANSPORT_ERROR',error_type=type(exc).__name__);self.breaker=True
        usage=valid_usage(record.get('provider_response',{}))
        record.update(seconds=time.monotonic()-started,known_tokens=usage or 0,
                      charged_tokens=usage if usage is not None else reservation,unknown_usage=usage is None)
        save(rawpath,record)
        self.ledger[key]={k:record[k] for k in ('status','charged_tokens','known_tokens','unknown_usage','name')}
        self.ledger[key]['raw_sha256']=hashlib.sha256(rawpath.read_bytes()).hexdigest()
        save(self.out/'ledger.json',self.ledger)
        if usage is None or sum(v['charged_tokens'] for v in self.ledger.values())>TOKEN_LIMIT:
            self.breaker=True
        print(json.dumps(dict(name=name,status=record['status'],attempts=len(self.ledger),
                             charged_tokens=sum(v['charged_tokens'] for v in self.ledger.values()))),flush=True)
        return record,None

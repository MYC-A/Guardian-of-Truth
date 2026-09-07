"""One-call safe Groq diagnostic: never prints server text, prompt or credentials."""
import argparse,hashlib,json
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler,build_opener

from guardian_truth.cli import read_rows
from guardian_truth.decomposition import EXTRACTOR_INSTRUCTION,EXTRACTOR_SCHEMA
from guardian_truth.llm_client import ChatClient,ClientConfig,HTTPResponse
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args): return None

def safe_rate_headers(headers):
    """Retain only documented quota counters/reset durations, never request metadata."""
    allowed=('retry-after','x-ratelimit-limit-requests','x-ratelimit-limit-tokens',
             'x-ratelimit-remaining-requests','x-ratelimit-remaining-tokens',
             'x-ratelimit-reset-requests','x-ratelimit-reset-tokens')
    lowered={str(key).casefold():str(value) for key,value in dict(headers or {}).items()}
    return {key:lowered[key] for key in allowed if key in lowered}

def main():
    p=argparse.ArgumentParser();p.add_argument('--env-file',type=Path,required=True)
    p.add_argument('--provider',choices=('groq','openrouter','gemini'),default='groq')
    p.add_argument('--model');args=p.parse_args()
    load_env_file(args.env_file)
    row=read_rows(Path('valid.parquet'))[0]
    summary={}
    def transport(request,timeout):
        try:
            response=build_opener(NoRedirect()).open(request,timeout=timeout)
            with response:
                body=response.read()
                summary['status']=response.status
                summary['body_bytes']=len(body)
                summary['body_sha256']=hashlib.sha256(body).hexdigest()
                summary['rate_headers']=safe_rate_headers(response.headers)
                return HTTPResponse(response.status,body,dict(response.headers))
        except HTTPError as error:
            with error:
                body=error.read(65537)
                summary['status']=error.code;summary['body_bytes']=len(body)
                summary['rate_headers']=safe_rate_headers(error.headers)
                summary['body_sha256']=hashlib.sha256(body).hexdigest()
                try:
                    value=json.loads(body)
                    summary['top_keys']=sorted(value) if isinstance(value,dict) else []
                    detail=value.get('error',{}) if isinstance(value,dict) else {}
                    if isinstance(detail,dict):
                        summary['error_keys']=sorted(detail)
                        for key in ('type','code','param'):
                            if detail.get(key) is None or isinstance(detail.get(key),(str,int,float,bool)):
                                summary[key]=detail.get(key)
                        message=detail.get('message','')
                        if isinstance(message,str):
                            lowered=message.casefold(); summary['message_chars']=len(message)
                            summary['message_sha256']=hashlib.sha256(message.encode()).hexdigest()
                            summary['message_flags']={word:word in lowered for word in
                                ('json','schema','reason','token','failed','generation','input','valid','strict',
                                 'day','daily','minute','retry','limit','requested','used','quota',
                                 'model','unavailable','overloaded','internal')}
                        failed=detail.get('failed_generation')
                        if isinstance(failed,str):
                            summary['failed_chars']=len(failed)
                            summary['failed_sha256']=hashlib.sha256(failed.encode()).hexdigest()
                            stripped=failed.strip()
                            summary['failed_shape']={'starts_object':stripped.startswith('{'),
                                'ends_object':stripped.endswith('}'),'has_code_fence':'```' in failed}
                            for label,candidate in [('whole',stripped),('object_slice',
                                    stripped[stripped.find('{'):stripped.rfind('}')+1])]:
                                try:
                                    parsed=json.loads(candidate)
                                    shape={'type':type(parsed).__name__}
                                    if isinstance(parsed,dict):
                                        shape['keys']=sorted(parsed)
                                        checks=parsed.get('checks')
                                        if isinstance(checks,list):
                                            shape['checks_count']=len(checks)
                                            shape['check_shapes']=[{k:type(v).__name__ for k,v in item.items()}
                                                for item in checks if isinstance(item,dict)][:20]
                                    summary[label+'_shape']=shape
                                except Exception: summary[label+'_json']=False
                except Exception: summary['json_body']=False
                return HTTPResponse(error.code,b'',dict(error.headers or {}))
    base=ClientConfig.from_env()
    selected_url=base.base_url if args.provider=='groq' else None
    config=provider_config(base,args.provider,model=args.model,base_url=selected_url)
    client=ChatClient(replace(config,max_output_tokens=2048,max_retries=0,strict_schema=True),transport=transport)
    try:
        completion=client.complete([{'role':'system','content':EXTRACTOR_INSTRUCTION},
                                    {'role':'user','content':json.dumps({'response':row['response']},ensure_ascii=False)}],
                                   schema=EXTRACTOR_SCHEMA,reasoning_effort='low')
        summary['usage']={key:value for key,value in completion.usage.items()
                          if key in ('prompt_tokens','completion_tokens','total_tokens')
                          and type(value) is int and value >= 0}
    except Exception: pass
    print(json.dumps(summary,sort_keys=True))
if __name__=='__main__':main()

"""Safely list model IDs for an explicitly selected compatible provider."""
import argparse
import json
import os
from pathlib import Path
from urllib.request import Request

from guardian_truth.llm_client import ChatClient,ClientConfig,_http_transport
from guardian_truth.parsing import decode_json
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider',choices=('openrouter','gemini'),required=True)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--contains',default='')
    parser.add_argument('--limit',type=int,default=40)
    args=parser.parse_args()
    if not 1 <= args.limit <= 200: parser.error('Invalid limit')
    load_env_file(args.env_file)
    try:
        config=provider_config(ClientConfig.from_env(),args.provider)
        ChatClient(config).validate_configuration()
        key=os.environ[config.api_key_env]
        request=Request(config.base_url.rstrip('/')+'/models',headers={
            'Authorization':'Bearer '+key,'Accept':'application/json',
            'User-Agent':'guardian-truth/0.2'},method='GET')
        response=_http_transport(request,30)
        if response.status != 200:
            print(json.dumps({'provider':args.provider,'status':response.status,'models':[]}))
            return 1
        payload,valid=decode_json(response.body.decode('utf-8'))
        rows=payload.get('data') if valid and isinstance(payload,dict) else None
        if not isinstance(rows,list): raise ValueError
        needle=args.contains.casefold()
        models=[]
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('id'),str): continue
            if needle and needle not in row['id'].casefold(): continue
            item={'id':row['id']}
            supported=row.get('supported_parameters')
            if isinstance(supported,list):
                item['supports']=[value for value in supported if value in
                    ('response_format','structured_outputs','reasoning')]
            models.append(item)
            if len(models) >= args.limit: break
        print(json.dumps({'provider':args.provider,'status':200,'matched':len(models),
                          'models':models},ensure_ascii=False))
        return 0
    except Exception:
        print(json.dumps({'provider':args.provider,'status':'local_or_parse_error','models':[]}))
        return 1


if __name__=='__main__':
    raise SystemExit(main())

"""Explicit tiny remote smoke test; never prints credentials or server bodies."""

import argparse
import json
from dataclasses import replace

from guardian_truth.settings import load_env_file
from guardian_truth.llm_client import ChatClient, ClientConfig, ChatClientError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='Make one tiny Groq request; otherwise only validate locally')
    parser.add_argument('--env-file',default='.env')
    parser.add_argument('--model',help='Explicit model override for a connection smoke test')
    args = parser.parse_args()
    load_env_file(args.env_file)
    try:
        config = replace(ClientConfig.from_env(),max_retries=0,max_output_tokens=512,timeout_seconds=15)
        if args.model:
            config = replace(config,model=args.model)
        client = ChatClient(config)
        client.validate_configuration()
        if not args.live:
            print(json.dumps({'configuration':'valid','authentication':'not_tested'}))
            return
        completion = client.complete([{'role':'user','content':'Return only a JSON object with connected equal to true.'}])
        print(json.dumps({'connection':'ok','model':completion.model,'usage':completion.usage}))
    except ChatClientError as error:
        print(json.dumps({'connection':'not_verified','category':error.category}))
        raise SystemExit(2)


if __name__ == '__main__':
    main()

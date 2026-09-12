"""One bounded B.AI connection probe; never serialize credentials or server errors."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from guardian_truth.llm_client import ChatClient, ChatClientError, ClientConfig, _http_transport
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('outputs/bai/smoke.json'))
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('refusing to overwrite an existing probe')
    if not args.env_file.is_file():
        raise ValueError('explicit env file does not exist')
    load_env_file(args.env_file)
    report = {'provider': 'bai', 'requested_model': 'qwen3.8-flash',
              'endpoint': 'https://api.b.ai/v1/chat/completions',
              'http_status': None, 'status': 'ERROR', 'error_category': None,
              'credential_values_serialized': False}

    def transport(request, timeout):
        response = _http_transport(request, timeout)
        report['http_status'] = response.status
        return response

    started = time.monotonic()
    try:
        config = provider_config(ClientConfig(timeout_seconds=180, max_output_tokens=2048,
                                             max_retries=0, response_format_mode='none'),
                                 'bai', model='qwen3.8-flash')
        client = ChatClient(config, transport=transport)
        client.validate_configuration()
        completion = client.complete([
            {'role': 'system', 'content': 'Return only a JSON object. Do not add explanation.'},
            {'role': 'user', 'content': 'Connection check. Return exactly {"ok":true}.\n'
             'OUTPUT_JSON_SCHEMA: {"type":"object","properties":{"ok":{"const":true}},'
             '"required":["ok"],"additionalProperties":false}'},
        ])
        report['served_model'] = completion.model
        answer = json.loads(completion.content)
        report['schema_valid'] = isinstance(answer, dict) and set(answer) == {'ok'} and answer['ok'] is True
        report['status'] = 'SUCCESS' if report['schema_valid'] else 'SCHEMA_INVALID'
        report['tokens'] = {key: value for key, value in completion.usage.items()
                            if key in ('prompt_tokens', 'completion_tokens', 'total_tokens')
                            and type(value) is int and value >= 0}
    except ChatClientError as error:
        report['error_category'] = error.category
    except (ValueError, TypeError):
        report['status'] = 'SCHEMA_INVALID'
    report['latency_ms'] = round((time.monotonic() - started) * 1000, 3)
    report['created_utc'] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['status'] == 'SUCCESS' else 1


if __name__ == '__main__':
    raise SystemExit(main())

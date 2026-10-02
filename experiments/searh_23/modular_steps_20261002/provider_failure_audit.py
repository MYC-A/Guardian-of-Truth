"""Read historical provider errors; export ONLY recognised parameter names.

No transport, no arbitrary provider strings, no environment values.
"""
import json
import re
import os
from collections import Counter
from pathlib import Path


def main():
    rows = [json.loads(s) for s in Path('/workspace/guardian/results/ta_cost_log.jsonl').read_text().splitlines()]
    result = Counter()
    examples = {}
    secrets = [v for k, v in os.environ.items() if any(w in k.upper() for w in ('KEY', 'TOKEN', 'PASSWORD', 'SECRET')) and v]
    for path in Path('/workspace/guardian/secrets').glob('*.env'):
        for line in path.read_text().splitlines():
            if '=' in line:
                secrets.append(line.split('=', 1)[1].strip().strip('\"\''))
    for row in rows:
        if not row.get('caller', '').startswith('modular/selfcheck/'):
            continue
        error = str(row.get('error', '')).lower()
        if error and row['model'] not in examples:
            safe = str(row['error'])
            for secret in secrets:
                if secret:
                    safe = safe.replace(secret, '[REDACTED]')
            safe = re.sub(r'https?://\S+', '[URL]', safe)
            safe = re.sub(r'[A-Za-z0-9_+./=-]{40,}', '[LONG_VALUE]', safe)
            examples[row['model']] = safe[:250]
        for name in ('seed', 'random_seed', 'temperature', 'response_format', 'max_tokens'):
            if name in error:
                result[(row['model'], name)] += 1
        if 'not supported' in error or 'unsupported' in error:
            result[(row['model'], 'unsupported_parameter')] += 1
        if 'extra_forbidden' in error or 'extra inputs are not permitted' in error:
            result[(row['model'], 'extra_parameter_forbidden')] += 1
        for reason in ('model', 'cloud', 'format', 'json', 'think', 'sampling', 'invalid', 'not found', 'incompatible', 'schema', 'currently', 'parallel', 'capacity', 'context'):
            if reason in error:
                result[(row['model'], 'reason_word/' + reason)] += 1
    print(json.dumps({'recognised_error_fields': [{'model': m, 'field': f, 'count': n} for (m, f), n in result.items()], 'sanitised_examples': examples}))


if __name__ == '__main__':
    main()

"""Provider-contract adaptation; no verdict aliases, JSON repair or semantic edits.

Ollama returned HTTP 200 but ignored the wire schema. Supply that exact schema
in the model-visible packet and allow stripping one enclosing JSON fence only.
Start on two dev cases before permitting the remaining frozen family holdout.
"""
import argparse
from copy import deepcopy
from pathlib import Path
import sys

ROOT = next((p for p in Path(__file__).resolve().parents if (p / 'src/guardian_truth').is_dir()),
            Path('/workspace/guardian/repos/semantic-hybrid-v4-20261004'))
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'experiments/research_v3'))
import pilot

original_ask = pilot.Client.ask


def unwrap_json_fence(content):
    text = content.strip()
    if text.startswith('```json\n') and text.endswith('\n```'):
        text = text[8:-4]
    elif text.startswith('```\n') and text.endswith('\n```'):
        text = text[4:-4]
    return text


def schema_in_packet(self, task, packet_value, schema=None, job=None):
    if job is not None:
        raise ValueError('THIS_ADAPTER_HAS_NO_GRAPH_ARM')
    packet_value = deepcopy(packet_value)
    packet_value['required_output_schema'] = schema.model_json_schema()
    packet_value['output_format_instruction'] = 'Return exactly one JSON object satisfying this schema; no markdown.'
    data, meta = original_ask(self, task, packet_value, schema, job)
    if data is not None or meta.get('status') != 'OK':
        return data, meta
    raw = pilot.read(self.out / 'raw' / (meta['request_sha256'] + '.json'))
    choice = raw['provider_response']['choices'][0]
    text = choice.get('message', {}).get('content')
    if choice.get('finish_reason') == 'stop' and isinstance(text, str):
        parsed, valid = pilot.decode_json(unwrap_json_fence(text))
        if valid and isinstance(parsed, dict):
            meta.pop('cause', None)
            meta['outer_json_fence_removed'] = text.strip() != unwrap_json_fence(text)
            return parsed, meta
    return data, meta


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['prepare', 'run', 'replay'])
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--limit', type=int)
    args = p.parse_args()
    args.model, args.provider, args.arms = 'gemma4:31b', 'ollama', ['A0', 'A2']
    pilot.Client.ask = schema_in_packet
    if args.phase == 'prepare':
        protocol = pilot.prepare(args)
        protocol.pop('protocol_sha256')
        protocol['arms'] = args.arms
        protocol['limits'] = {'http': 80, 'tokens': 230000}
        protocol['diagnostic'] = {'adapter_sha256': pilot.sha(Path(__file__)),
                                  'wire': 'EXACT_SCHEMA_IN_PACKET_SINGLE_OUTER_JSON_FENCE_STRIP',
                                  'scope': 'DEV_CAPABILITY_THEN_UNCHANGED_FAMILY_HOLDOUT',
                                  'control': 'Separate provider-contract replication, not original strict-wire result'}
        protocol['protocol_sha256'] = pilot.digest(protocol)
        pilot.write(args.out / 'protocol.json', protocol)
        print(protocol['protocol_sha256'])
    else:
        protocol = pilot.read(args.out / 'protocol.json')
        if protocol['diagnostic']['adapter_sha256'] != pilot.sha(Path(__file__)):
            raise ValueError('ADAPTER_CHANGED')
        if args.limit:
            original_inputs = pilot.inputs
            pilot.inputs = lambda path: original_inputs(path)[:args.limit]
        print(pilot.infer(args))

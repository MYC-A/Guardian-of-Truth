"""Development-only diagnostics of existing ID graph and A0 schema enums.

No primary prompt/code mutation, no gold loading, no replacement of old replies.
This measures bundled ID/arity admission, not independent semantic completeness.
"""
import argparse
from copy import deepcopy
from pathlib import Path
import sys

ROOT = next((p for p in Path(__file__).resolve().parents if (p / 'src/guardian_truth').is_dir()),
            Path('/workspace/guardian/repos/semantic-hybrid-v4-20261004'))
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'experiments/research_v3'))
sys.path.insert(0, str(ROOT / 'experiments/searh_23/evidence_graph_search_probe'))
import pilot
from span_ids import IdGraph
from guardian_truth.source_search.store import SourceStore

original_inputs = pilot.inputs
pilot.inputs = lambda path: [r for r in original_inputs(path) if r['id'].split('.')[0] in ('custody', 'reagent')]


class DirectEnums:
    """The contextual prompt is unchanged; allowed IDs are supplied by code."""
    registry = None

    @classmethod
    def model_json_schema(cls):
        schema = deepcopy(pilot.Direct.model_json_schema())
        refs = cls.registry['sources']
        schema['properties']['policy_ids']['items']['enum'] = [sid for sid, s in refs.items() if s['kind'] == 'policy']
        schema['properties']['evidence_ids']['items']['enum'] = list(refs)
        return schema


original_ask = pilot.Client.ask


def enum_ask(self, task, packet_value, schema=None, job=None):
    if task == 'A0':
        DirectEnums.registry = packet_value
        schema = DirectEnums
    return original_ask(self, task, packet_value, schema, job)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare', 'run', 'replay'])
    parser.add_argument('--control', choices=['graph_ids', 'context_enums'], required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.model, args.provider = 'ministral-14b-latest', 'mistral'
    args.arms = ['A1'] if args.control == 'graph_ids' else ['A0']
    if args.control == 'graph_ids':
        pilot.make_graph = lambda row: IdGraph(SourceStore({'prompt': row['prompt'], 'response': row['response']}))
    else:
        pilot.Client.ask = enum_ask
    if args.phase == 'prepare':
        protocol = pilot.prepare(args)
        protocol.pop('protocol_sha256')
        protocol['arms'] = args.arms
        protocol['limits'] = {'http': 60, 'tokens': 180000} if args.control == 'graph_ids' else {'http': 16, 'tokens': 40000}
        protocol['diagnostic'] = {'control': args.control, 'scope': 'DEV_ONLY_NO_HELDOUT_LABELS',
                                  'selection': ['custody', 'reagent'],
                                  'adapter_sha256': pilot.sha(Path(__file__)),
                                  'id_graph_sha256': pilot.sha(ROOT / 'experiments/searh_23/evidence_graph_search_probe/span_ids.py')}
        protocol['protocol_sha256'] = pilot.digest(protocol)
        pilot.write(args.out / 'protocol.json', protocol)
        print(protocol['protocol_sha256'])
    else:
        protocol = pilot.read(args.out / 'protocol.json')
        if protocol['diagnostic']['adapter_sha256'] != pilot.sha(Path(__file__)):
            raise ValueError('DIAGNOSTIC_ADAPTER_CHANGED')
        print(pilot.infer(args))

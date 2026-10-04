"""Contextual-only continuation after its provider contract passed two dev cases.

The failed local compiler is excluded prospectively; no primary result is replaced.
Same schema-in-packet transformation, same original A0 prompt, same 32-case suite.
"""
import argparse
import importlib.util
from pathlib import Path
import sys

ROOT = next((p for p in Path(__file__).resolve().parents if (p / 'src/guardian_truth').is_dir()),
            Path('/workspace/guardian/repos/semantic-hybrid-v4-20261004'))
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'experiments/research_v3'))
import pilot

adapter = Path(__file__).with_name('gemma_contract.py')
if not adapter.exists():
    adapter = Path('/tmp/guardian_v4_gemma_contract.py')
spec = importlib.util.spec_from_file_location('gemma_contract_adapter', adapter)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
pilot.Client.ask = module.schema_in_packet

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['prepare', 'run', 'replay']); p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    args.model, args.provider, args.arms = 'gemma4:31b', 'ollama', ['A0']
    if args.phase == 'prepare':
        protocol = pilot.prepare(args); protocol.pop('protocol_sha256')
        protocol['arms'] = ['A0']; protocol['limits'] = {'http': 32, 'tokens': 80000}
        protocol['diagnostic'] = {'adapter_sha256': pilot.sha(Path(__file__)),
                                  'provider_contract_sha256': pilot.sha(adapter),
                                  'control': 'FROZEN_A0_WITH_SCHEMA_IN_PACKET; DEV_CONTRACT_PASSED; HELDOUT_NOT_USED_FOR_ADAPTATION',
                                  'scope': 'FULL_32_CASE_CONTEXTUAL_ONLY'}
        protocol['protocol_sha256'] = pilot.digest(protocol)
        pilot.write(args.out / 'protocol.json', protocol); print(protocol['protocol_sha256'])
    else:
        protocol = pilot.read(args.out / 'protocol.json')
        if protocol['diagnostic']['adapter_sha256'] != pilot.sha(Path(__file__)) or protocol['diagnostic']['provider_contract_sha256'] != pilot.sha(adapter):
            raise ValueError('CONTEXTUAL_ADAPTER_CHANGED')
        print(pilot.infer(args))

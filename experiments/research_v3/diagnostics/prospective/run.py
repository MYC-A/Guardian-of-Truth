"""Same contextual prompt/provider adapter on two new families; no gold access."""
import argparse
import importlib.util
from pathlib import Path
import sys

ROOT = next((p for p in Path(__file__).resolve().parents if (p / 'src/guardian_truth').is_dir()),
            Path('/workspace/guardian/repos/semantic-hybrid-v4-20261004'))
sys.path.insert(0, str(ROOT / 'src')); sys.path.insert(0, str(ROOT / 'experiments/research_v3'))
import pilot

local_dir = Path(__file__).parent
adapter = local_dir.parent / 'gemma_contract.py'
if not adapter.exists():
    adapter = Path('/tmp/guardian_v4_gemma_contract.py')
spec = importlib.util.spec_from_file_location('provider_contract_adapter', adapter)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
base_code = pilot.fingerprints()
pilot.HERE = local_dir
pilot.fingerprints = lambda: {**base_code, 'prospective/run.py': pilot.sha(Path(__file__)),
                             'prospective/build.py': pilot.sha(local_dir / 'build.py'),
                             'provider_contract_adapter.py': pilot.sha(adapter)}
pilot.Client.ask = module.schema_in_packet

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['prepare', 'run', 'replay']); p.add_argument('--out', type=Path, required=True)
    args = p.parse_args(); args.model, args.provider, args.arms = 'gemma4:31b', 'ollama', ['A0']
    if args.phase == 'prepare':
        protocol = pilot.prepare(args); protocol.pop('protocol_sha256')
        protocol['arms'] = ['A0']; protocol['limits'] = {'http': 16, 'tokens': 40000}
        protocol['data_status'] = 'PROSPECTIVE_TWO_NEW_AUTHOR_CONTROLLED_FAMILIES; NO_EXTERNAL_BLINDING'
        protocol['hypothesis'] = 'Selective chronology rejection may help prerequisite rules but over-abstain for immutable state facts.'
        protocol['guard_sha256'] = pilot.sha(local_dir / 'source_guard.py')
        protocol['protocol_sha256'] = pilot.digest(protocol)
        pilot.write(args.out / 'protocol.json', protocol); print(protocol['protocol_sha256'])
    else:
        print(pilot.infer(args))

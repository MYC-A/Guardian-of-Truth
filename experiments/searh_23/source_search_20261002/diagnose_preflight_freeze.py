"""Read-only diagnostics of a cross-platform freeze, no labels or inference."""
import json
from pathlib import Path
import sys

repo = Path(sys.argv[1])
sys.path.insert(0, str(repo / 'experiments/searh_23/source_search_20261002'))
from model_preflight import ROOT, OUT, identity, digest

original = json.loads((OUT / 'frozen.json').read_text(encoding='utf-8'))
rows = [json.loads(line) for line in
        (ROOT / 'outputs/searh_23/source_search_20261002/transfer_v1/inputs.jsonl').read_text(encoding='utf-8').splitlines()]
current = {'input_sha256': digest([rows[i] for i in (0,1,8,9,20,21)]),
    'runner_sha256': digest((repo / 'experiments/searh_23/source_search_20261002/model_preflight.py').read_text(encoding='utf-8')),
    'code_sha256': identity()}
print(json.dumps({'fingerprints': {k:{'original':original.get(k),'current':v,
                                    'matches':original.get(k)==v} for k,v in current.items()}}))

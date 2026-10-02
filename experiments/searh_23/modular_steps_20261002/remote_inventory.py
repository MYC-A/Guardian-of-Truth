"""Safe read-only inventory; prints model IDs and hashes, never credentials."""
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, '/workspace/guardian/repos/hybrid-service-worktree/experiments/searh_23/three_architectures')
import llm

print(json.dumps({'default_mistral_model': llm.DEFAULT_MISTRAL_MODEL,
                  'providers_configured': {p: bool(pair[1]) for p, pair in llm.PROVIDERS.items()}}))
for provider in ('mistral', 'ollama'):
    try:
        _, client = llm._client(provider + '/inventory-no-inference')
        names = sorted(m.id for m in client.models.list().data)
        if provider == 'mistral':
            names = [m for m in names if any(k in m.lower() for k in ('codestral', 'devstral', 'ministral', 'small', 'large', 'magistral'))]
        print(json.dumps({'provider': provider, 'model_ids': names, 'probe': 'GET_models_not_generation'}))
    except Exception as exc:
        print(json.dumps({'provider': provider, 'error_type': type(exc).__name__, 'http_status': getattr(exc, 'status_code', None)}))
for root in (Path('/workspace/.hf_home/hub'), Path('/workspace/guardian/hf_cache/hub')):
    blobs = []
    for path in root.glob('models--*/*/*'):
        if path.is_file() and not path.is_symlink() and path.stat().st_size > 500_000_000:
            h = hashlib.sha256()
            with path.open('rb') as f:
                for block in iter(lambda: f.read(8 << 20), b''):
                    h.update(block)
            blobs.append({'path': str(path), 'bytes': path.stat().st_size, 'sha256': h.hexdigest(),
                          'device': path.stat().st_dev, 'inode': path.stat().st_ino})
    print(json.dumps({'cache_root': str(root), 'large_files': blobs}))

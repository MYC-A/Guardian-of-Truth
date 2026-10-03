"""Read-only instance receipt; credential values are never serialized."""
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def inspect():
    guide = Path('/etc/vast-agents-guide.md')
    result = {'guide_sha256': hashlib.sha256(guide.read_bytes()).hexdigest(),
        'python': sys.version.split()[0], 'python_executable': sys.executable}
    packages = {}
    for name in ('pydantic', 'pytest', 'pyarrow', 'numpy', 'torch', 'openai'):
        try: packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError: packages[name] = None
    result['packages'] = packages
    if packages['torch']:
        import torch
        result['cuda_available'] = torch.cuda.is_available()
        if result['cuda_available']:
            result['small_cuda_op'] = float(torch.ones(1, device='cuda').sum().item())
            result['gpu'] = torch.cuda.get_device_name(0)
    loaded = {}
    names = ('MISTRAL_API_KEY', 'MISTRAL_MODEL', 'OLLAMA_API_KEY', 'UKISAI_API_KEY')
    files = []
    for path in (Path('/workspace/.env'), Path('/workspace/guardian/secrets/mistral.env'),
                 Path('/workspace/guardian/secrets/api_keys.env')):
        if not path.exists(): continue
        files.append(str(path))
        for line in path.read_text().splitlines():
            line = line.strip().removeprefix('export ')
            if not line or line.startswith('#') or '=' not in line: continue
            name, value = line.split('=', 1)
            if name.strip() in names: loaded[name.strip()] = value.strip().strip('"').strip("'")
    result['credential_files_present'] = files
    result['credentials_presence'] = {name: bool(os.environ.get(name) or loaded.get(name)) for name in names if name.endswith('_KEY')}
    result['configured_mistral_model'] = os.environ.get('MISTRAL_MODEL') or loaded.get('MISTRAL_MODEL')
    ledgers = []
    for path in sorted(Path('/workspace/guardian/results').rglob('budget.sqlite')):
        with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as db:
            try:
                calls, known, unknown, pending = db.execute('SELECT COUNT(*),COALESCE(SUM(known_tokens),0),COALESCE(SUM(unknown_bound),0),'
                    "COALESCE(SUM(status='RESERVED'),0) FROM attempts").fetchone()
            except sqlite3.OperationalError: continue
        ledgers.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'calls': calls, 'known_tokens': known, 'unknown_bounds': unknown, 'pending': pending,
            'breaker_present': (path.parent / 'breaker.json').exists()})
    result['prior_ledgers_read_only'] = ledgers
    capabilities = json.loads(subprocess.check_output(['vast-capabilities']))
    result['workspace_is_volume'] = capabilities.get('instance', {}).get('workspace_is_volume')
    result['existing_main_repo_head'] = subprocess.check_output(['git', '-C', '/workspace/guardian/repos/Guardian-of-Truth',
        'rev-parse', 'HEAD'], text=True).strip()
    return result


if __name__ == '__main__': print(json.dumps(inspect(), sort_keys=True))

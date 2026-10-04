"""Read-only server orientation; never prints credentials or process arguments."""
import json
import os
from pathlib import Path
import subprocess

guide = Path('/workspace/AGENTS.md')
if guide.exists():
    print('GUIDE_LINES_150_205\n' + '\n'.join(guide.read_text().splitlines()[149:205]))
root = Path('/workspace/guardian')
paths = sorted(set(root.glob('*.env')) | set(root.glob('secrets/*.env')) |
               set(Path('/workspace').glob('.env')))
print('CREDENTIAL_FILE_PATHS', [str(p) for p in paths])
for p in paths:
    names = [s.strip().removeprefix('export ').split('=', 1)[0].strip()
             for s in p.read_text().splitlines() if '=' in s and not s.strip().startswith('#')]
    print('CREDENTIAL_NAMES', str(p), names)
print('ENV_CREDENTIAL_NAMES', [k for k in os.environ if 'API_KEY' in k or k == 'MISTRAL_MODEL'])
print('RECENT_RESULT_DIRS', [p.name for p in (root / 'results').iterdir()][-20:])
for p in (root / 'repos').glob('*/AGENTS.md'):
    print('REPO_GUIDE', str(p), p.read_text())
try:
    import pydantic
    print('PYDANTIC', pydantic.__version__)
except ImportError:
    print('PYDANTIC_NOT_INSTALLED')

"""Explicit local dotenv loading; no shell evaluation, expansion or global writes."""

import os
from pathlib import Path


def load_env_file(path: Path | str = '.env') -> bool:
    path = Path(path)
    if not path.is_file():
        return False
    allowed = {'GROQ_API_KEY', 'GUARDIAN_API_KEY', 'GUARDIAN_MODEL', 'GUARDIAN_BASE_URL',
               'GUARDIAN_LOCAL_API_KEY', 'GUARDIAN_LOCAL_BASE_URL',
               'GUARDIAN_LLM_BASE_URL', 'GUARDIAN_LLM_MODEL', 'GUARDIAN_LLM_API_KEY_ENV',
               'GUARDIAN_LLM_TIMEOUT_SECONDS', 'GUARDIAN_LLM_MAX_OUTPUT_TOKENS',
               'GUARDIAN_LLM_MAX_RETRIES', 'GUARDIAN_LLM_STRICT_SCHEMA'}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name, separator, value = line.partition('=')
        name, value = name.strip(), value.strip()
        if not separator or name not in allowed:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(name, value)
    return True

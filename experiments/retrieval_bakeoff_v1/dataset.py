"""Frozen original-row inputs; scorer labels and references stay separate."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name('fixtures') / 'manifest.json'


def load_cases(split=None, path=None):
    """Return exactly id/prompt/response/split, never gold or explanations.

    The historical validation set is diagnostic, including the evaluation split.
    A path override must contain the frozen originals, rather than edited rows.
    """
    import pandas as pd
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if split is not None and split not in ('dev', 'evaluation_known'):
        raise ValueError('UNKNOWN_FROZEN_SPLIT')
    frame = pd.read_parquet(Path(path) if path is not None else ROOT / manifest['dataset'])
    if frame['id'].duplicated().any():
        raise ValueError('DUPLICATE_ORIGINAL_ID')
    originals = frame.set_index('id')
    result = []
    for entry in manifest['cases']:
        if split is not None and entry['split'] != split:
            continue
        row = originals.loc[entry['id']]
        record = {key: str(row[key]) for key in ('prompt', 'response')}
        actual = hashlib.sha256(json.dumps(record, ensure_ascii=False,
            sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        if actual != entry['input_sha256']:
            raise ValueError('FROZEN_ORIGINAL_INPUT_CHANGED')
        result.append({'id': entry['id'], **record, 'split': entry['split']})
    return result

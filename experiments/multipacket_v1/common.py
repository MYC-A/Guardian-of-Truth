"""Shared data access for the multi-packet / gap-controller study (no gold reaches inference code)."""
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/multipacket_v1'


@lru_cache(None)
def valid_rows():
    import pandas as pd
    d = pd.read_parquet(ROOT / 'valid.parquet')
    return tuple(dict(id=r.id, prompt=r.prompt, response=r.response) for r in d.itertuples())


@lru_cache(None)
def valid_gold():
    """EVALUATION ONLY."""
    import pandas as pd
    d = pd.read_parquet(ROOT / 'valid.parquet')
    return {r.id: dict(label=int(r.label), explanation=r.explanation if isinstance(r.explanation, str) else None) for r in d.itertuples()}


@lru_cache(None)
def references():
    """EVALUATION / ORACLE ONLY."""
    return json.loads((ROOT / 'experiments/retrieval_bakeoff_v1/fixtures/references.json').read_text())


@lru_cache(None)
def baseline_cache():
    return json.loads((OUT / 'baseline_cache/u2_replies.json').read_text())


def baseline_reply(arm, row_id, run=1):
    return baseline_cache().get(f'{arm}/{row_id}|run{run}')

"""Seed a read-only replay cache for baseline A on the six dev rows copied from frozen120 (P08/P09): the saved R_fix
live records (outputs/guardian_v6_fix/runs_r/hold_frozen120/rep1_R_fix_live.jsonl, attempt 0) contain the raw reply of
their only model call ('review'); the cache key is the hash of the exact request, so run_v5 replays it only if today's
request is byte-identical (otherwise a miss). Each entry is marked replay_of."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'outputs/guardian_v6_fix/runs_r/hold_frozen120/rep1_R_fix_live.jsonl'
DST = ROOT / 'outputs/guardian_semantic/cache/replay_frozen120'

for r in map(json.loads, SRC.read_text(encoding='utf-8').splitlines()):
    if not ('_P08_' in r['id'] or '_P09_' in r['id']):
        continue
    steps = r['A']['steps']
    assert len(steps) == 1 and r['triggers'] and not r['pool']
    s = steps[0]
    p = DST / s['key'][:2] / f"{s['key']}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dict(key=s['key'], request_sha256=s['request_sha256'], attempt=0, model='ministral-14b-2512', tag='review',
                                 usage=s.get('usage'), transport=s.get('transport'), finish_reason=s.get('finish_reason'),
                                 response_model=s.get('response_model'), content=s['raw_content'],
                                 replay_of=f"{SRC.relative_to(ROOT)}#{r['id']}"), ensure_ascii=False))
    print(r['id'], s['key'][:12])

"""Repair the deferred-bank gold provenance (assignment 2026-10-02 §3.4).

def_mixed::01 carried a fabricated policy_span quote
('Report only facts supported by preceding observations for the requested item.')
that appears nowhere in the case sources. The real basis of the gold label:
the catalog entry for inspect defines status=success (a tool-RESULT field) as
inspection succeeded, and the history contains NO inspect TOOL_RESPONSE — the
target's own inspect call is the request itself. The success assertion is
therefore unsupported (assertion not justified by context). Label unchanged
(ERROR); only provenance is repaired.

Bank versioning: manifest schema deferred-bank/2 with an explicit changelog;
the previous gold is preserved verbatim as author_gold_v1.jsonl and stays
retrievable from git history. Input rows are never touched (input_sha256
pinned). All other 23 gold lines must remain byte-identical (asserted).
"""
import json
import shutil
import sys
from pathlib import Path

from modular_common import HERE, sha

BANK = HERE / 'dataset' / 'deferred_bank'
TARGET = 'def_mixed::01'
REAL_CATALOG_SPAN = 'status=success means inspection succeeded; status=failed means it did not'


def main():
    inp = (BANK / 'input.jsonl').read_text(encoding='utf-8')
    gold_lines = (BANK / 'author_gold.jsonl').read_text(encoding='utf-8').splitlines()
    old_manifest = json.loads((BANK / 'manifest.json').read_text(encoding='utf-8'))
    assert sha(inp.encode()) == old_manifest['input_sha256'], 'input drifted before gold repair'
    assert old_manifest.get('schema') == 'deferred-bank/1', 'unexpected manifest schema'

    rows = [json.loads(l) for l in (BANK / 'input.jsonl').read_text(encoding='utf-8').splitlines()]
    case = next(r for r in rows if r['id'] == TARGET)
    assert REAL_CATALOG_SPAN in case['prompt'], 'real catalog span not found in the source'
    fabricated = 'Report only facts supported by preceding observations for the requested item.'
    assert fabricated not in case['prompt'], 'fabricated quote unexpectedly present now'

    # preserve the old gold verbatim before any edit
    v1_path = BANK / 'author_gold_v1.jsonl'
    if not v1_path.exists():
        shutil.copyfile(BANK / 'author_gold.jsonl', v1_path)
    assert sha(v1_path.read_bytes()) == old_manifest['gold_sha256'], 'v1 copy does not match old manifest'

    fixed, changed = [], []
    for line in gold_lines:
        g = json.loads(line)
        if g['id'] != TARGET:
            fixed.append(line)
            continue
        assert g['label'] == 1 and g['expected_decision'] == 'ERROR'
        old_quote = (g.get('policy_span') or {}).get('quote', '')
        assert old_quote == fabricated, f'unexpected old quote: {old_quote!r}'
        g = dict(g)
        g['requirement'] = {
            'kind': 'UNSUPPORTED_ASSERTION',
            'specification': {
                'claim': 'The inspection of item E-70 has succeeded',
                'basis': 'catalog status vocabulary + absence of any inspect TOOL_RESPONSE in the preceding history',
            },
        }
        g['reason'] = ('MIXED target: the inspect call is a REQUEST; the catalog defines '
                       'status=success (a tool-result field) as inspection succeeded; no inspect '
                       'TOOL_RESPONSE exists in the preceding history, so the asserted completion '
                       'is unsupported (assertion not justified by context)')
        g['policy_span'] = {'quote': REAL_CATALOG_SPAN, 'source': 'prompt'}
        g['provenance'] = (g.get('provenance', '') +
                           '; policy_span repaired 2026-10-02 (all-methods assignment §3.4): '
                           'fabricated quote replaced by the real catalog basis; label unchanged; '
                           'see manifest changelog v2')
        changed.append(g['id'])
        fixed.append(json.dumps(g, ensure_ascii=False, sort_keys=True))
    assert changed == [TARGET], changed

    old_lines = [l for l in gold_lines]
    new_lines = fixed
    diff = [(i, a, b) for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
    assert len(diff) == 1 and diff[0][0] == [json.loads(l)['id'] for l in gold_lines].index(TARGET)
    for i, a, b in diff:
        ga, gb = json.loads(a), json.loads(b)
        assert ga['label'] == gb['label'] and ga['id'] == gb['id'], 'label changed — forbidden'
    (BANK / 'author_gold.jsonl').write_text('\n'.join(new_lines) + '\n', encoding='utf-8')

    new_manifest = dict(old_manifest)
    new_manifest['schema'] = 'deferred-bank/2'
    new_manifest['version'] = 2
    new_manifest['gold_sha256'] = sha((BANK / 'author_gold.jsonl').read_bytes())
    new_manifest['superseded_version'] = {
        'schema': old_manifest['schema'],
        'gold_sha256': old_manifest['gold_sha256'],
        'preserved_as': 'author_gold_v1.jsonl (byte-identical copy, also retrievable from git history)',
    }
    new_manifest['changelog'] = [
        {'version': 1, 'change': 'initial 24-case new-construction bank (author gold, PENDING human review)'},
        {'version': 2, 'date': '2026-10-02',
         'change': ('def_mixed::01 policy_span repaired per all-methods assignment §3.4: the fabricated '
                    'quote was replaced by the real catalog span; requirement kind PERMISSION->'
                    'UNSUPPORTED_ASSERTION with the real basis; label and all other 23 gold lines '
                    'byte-identical; input.jsonl untouched'),
         'label_impact': 'none (def_mixed::01 was never measured in the 18 complete triples; label unchanged)'},
    ]
    (BANK / 'manifest.json').write_text(
        json.dumps(new_manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')

    print(json.dumps({
        'repaired': changed,
        'old_gold_sha256': old_manifest['gold_sha256'],
        'new_gold_sha256': new_manifest['gold_sha256'],
        'input_sha256_unchanged': sha(inp.encode()) == old_manifest['input_sha256'],
        'v1_preserved': str(v1_path),
        'other_lines_unchanged': sum(1 for a, b in zip(old_lines, new_lines) if a == b) == 23,
    }, indent=1))


if __name__ == '__main__':
    sys.exit(main())

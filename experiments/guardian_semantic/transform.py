"""Robustness set devT (written after the dev/frozen runs, before running it): 8 dev rows (P08x3, P09x3, controls D3, D4)
with two meaning-preserving transforms applied to prompt AND response alike:
  ID rename   : every digit run (>=3 digits) directly preceded by a letter, '#', '_' or '-' gets each digit mapped by
                d -> (7d+3) mod 10 (a bijection; consistent across the row, so all relations are kept);
  permutation : a TOOL_RESPONSE whose payload is a top-level JSON list of >=2 objects is reversed (record order only).
Gold: label/family/target unchanged; cause markers renamed with the same map. python -m experiments.guardian_semantic.transform"""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / 'outputs/guardian_semantic/data'
IDS = ['v6fx_P08_computed_amount_wrong_tel', 'v6fx_P08_computed_amount_wrong_ret', 'v6fx_P08_computed_amount_wrong_bank',
       'v6fx_P09_other_entity_id_tel', 'v6fx_P09_other_entity_id_ret', 'v6fx_P09_other_entity_id_bank',
       'sem_D3_namesake_ok_bank', 'sem_D4_household_ok_tel']
RX = re.compile(r'(?<=[A-Za-z#_\-])(\d{3,})(?!\d)(?!\.\d)')
LINE = re.compile(r'^(\s*← TOOL_RESPONSE [^:]+: )(\[.*\])[ \t]*$', re.M)


def rename(s):
    return RX.sub(lambda m: ''.join(str((7 * int(c) + 3) % 10) for c in m.group(1)), s)


def permute(s):
    def f(m):
        try:
            v = json.loads(m.group(2))
        except Exception:
            return m.group(0)
        if len(v) >= 2 and all(isinstance(x, dict) for x in v):
            return m.group(1) + json.dumps(v[::-1], ensure_ascii=False)
        return m.group(0)
    return LINE.sub(f, s)


def main():
    rows = {r['id']: r for r in map(json.loads, (D / 'dev_inputs.jsonl').read_text(encoding='utf-8').splitlines())}
    gold = json.loads((D / 'dev_GOLD.json').read_text(encoding='utf-8'))
    assert not (D / 'devT_inputs.jsonl').exists(), 'refusing to overwrite'
    out, g = [], {}
    for i in IDS:
        r = rows[i]
        t = dict(id=i + '__T', prompt=permute(rename(r['prompt'])), response=permute(rename(r['response'])))
        assert t['prompt'] != r['prompt']
        out.append(t)
        g[t['id']] = dict(gold[i], cause_markers=[rename(m) for m in gold[i]['cause_markers']], cause=rename(gold[i]['cause']),
                          split='devT', source_row=i)
    (D / 'devT_inputs.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in out), encoding='utf-8')
    (D / 'devT_GOLD.json').write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding='utf-8')
    for x in out:
        print(x['id'], 'permuted' if permute(rename(rows[x['id'][:-3]]['prompt'])) != rename(rows[x['id'][:-3]]['prompt']) else '-')


if __name__ == '__main__':
    main()

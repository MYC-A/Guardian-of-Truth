"""Build the fresh lockbox LB1 (authored 2026-10-06 BEFORE any verification-v2 mechanism code).
python -m experiments.verification_v2.lockbox.build  -> outputs/verification_v2/lockbox/
inputs.jsonl carries only opaque id/prompt/response; GOLD_eval_only.json is read only by the scorer."""
import hashlib, json, random
from pathlib import Path

from . import d_pharmacy, d_rental, d_university, d_itdesk, d_insurance, d_utility
from . import e_hotel, e_gym, e_tickets, e_courier
from . import f_telecom, f_bank, f_clinic, f_autoservice
SETS = {'lb1': (d_pharmacy, d_rental, d_university, d_itdesk, d_insurance, d_utility), 'lb2': (e_hotel, e_gym, e_tickets, e_courier),
        'lb3': (f_telecom, f_bank, f_clinic, f_autoservice)}
from .fmt import render
from .padding import pad

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'outputs/verification_v2/lockbox'


def build(long=False, name='lb1'):
    rows, gold = [], {}
    for mod in SETS[name]:
        policy, tools, cases = mod.cases()
        for c in cases:
            pol, hist = pad(mod.DOMAIN, policy, c['history']) if long else (policy, c['history'])
            prompt, resp = render(pol, tools, hist, c['response'])
            rows.append(dict(case=c['id'], prompt=prompt, response=resp))
            gold[c['id']] = {k: c[k] for k in ('domain', 'family', 'label', 'target', 'cause', 'pair', 'keys')}
    rng = random.Random({'lb1': 20261006, 'lb2': 20261007, 'lb3': 20261008}[name])
    rng.shuffle(rows)
    out, g2 = [], {}
    for i, r in enumerate(rows):
        oid = f'{name}{"L" if long else ""}_{i:03d}'
        out.append(dict(id=oid, prompt=r['prompt'], response=r['response']))
        g2[oid] = dict(case=r['case'], **gold[r['case']])
    return out, g2


def write(long, name='lb1'):
    rows, gold = build(long, name)
    out = {'lb1': OUT, 'lb2': OUT.parent / 'lockbox2', 'lb3': OUT.parent / 'lockbox3'}[name] / ('long' if long else 'short')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'inputs.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    (out / 'GOLD_eval_only.json').write_text(json.dumps(gold, ensure_ascii=False, indent=1))
    h = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (out / 'inputs.jsonl', out / 'GOLD_eval_only.json')}
    (out / 'MANIFEST.json').write_text(json.dumps(dict(rows=len(rows), positives=sum(g['label'] for g in gold.values()), sha256=h), indent=1))
    print(out.name, len(rows), sum(g['label'] for g in gold.values()), h)


if __name__ == '__main__':
    write(False)
    write(True)
    write(True, 'lb2')
    write(True, 'lb3')

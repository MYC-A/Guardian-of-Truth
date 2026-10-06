"""Layer F on all dev sets: extract turn-shape rules per unique policy (cached), check every row mechanically."""
import hashlib, json, sys
from collections import Counter, defaultdict
from guardian_truth.integrated import Transport
from guardian_truth.repair.clients import ReadThrough
from guardian_truth.verification.pipeline import packet_for
from guardian_truth.v6 import turnrules as F
from experiments.universal_repair.run import OUT, MODEL, inputs, paced
from experiments.universal_repair.score import gold_for

V6 = OUT.parent / 'guardian_v6'
SETS = sys.argv[1:] or ['valid46', 'lb_long', 'lb2_long', 'lb3_long', 'ext_tau2', 'hold_tau2h']


def main():
    live = Transport('mistral', MODEL, V6 / 'cache' / 'frules', max_calls=300, retry_failed=2, sender=paced)
    client = ReadThrough('mistral', MODEL, [], live=live)
    rules_by = {}
    out = open(V6 / 'flayer.jsonl', 'w', encoding='utf-8')
    for s in SETS:
        g = gold_for(s); c = Counter()
        for r in inputs(s):
            p = packet_for(r, 400000)
            h = hashlib.sha256(json.dumps([x['text'] for x in p['normative_sources']]).encode()).hexdigest()[:16]
            if h not in rules_by:
                rules_by[h] = F.extract(client, MODEL, p['normative_sources'])
            rules, meta = rules_by[h]
            cands = F.check(rules, p['current_targets'])
            lab = (g.get(r['id']) or {}).get('label')
            c[(bool(cands), lab)] += 1
            out.write(json.dumps(dict(set=s, id=r['id'], label=lab, policy=h, rules=rules, fired=[x['kind'] for x in cands],
                                      reason=[x['reason'] for x in cands]), ensure_ascii=False) + '\n')
        print(s, dict(c), flush=True)
    for h, (rules, meta) in rules_by.items():
        print(h, [(x['type'], x['n'], x['quote'][:90]) for x in rules], meta.get('a'), meta.get('b'))
    print(live.counts)


if __name__ == '__main__':
    main()

"""Theory test G1: does the existing verifier separate grounded from ungrounded reviewer (A) accusations?
For every unique (set,id,accusation) R_fix positive owned by A_adm2/GUARD, verify the accusation itself; cross-tab with
judge-v2 category and label. Live, separate cache outputs/guardian_v6/cache/ground."""
import json, re, sys, threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from guardian_truth.integrated import Transport
from guardian_truth.repair.clients import ReadThrough
from guardian_truth.repair.v5 import ARMS, verify, decide
from guardian_truth.verification.pipeline import packet_for
from experiments.universal_repair.run import OUT, MODEL, inputs, paced
from experiments.universal_repair.judge_v2 import positives, load

V6 = OUT.parent / 'guardian_v6'


def cand_of(acc, rp):
    t = acc.get('text') or ''
    tids = [x['source_id'] for x in rp['current_targets']]
    pol = {s['source_id'] for s in rp['normative_sources']}
    allids = {s['source_id'] for k in ('history', 'current_targets', 'declarations') for s in rp[k]}
    ids = re.findall(r'\b([qhtd]\d+)\b', t)
    return dict(origin='A', target_id=acc.get('target_id') if acc.get('target_id') in tids else tids[0], requirement='',
                reason=t[:1500], policy_source_ids=[i for i in dict.fromkeys(ids) if i in pol],
                evidence_source_ids=[i for i in dict.fromkeys(ids) if i in allids])


def main():
    J = load(OUT.parent / 'universal_repair_v2' / 'cause' / 'judgements_v2_a0.jsonl')
    rows = {}
    todo, seen = [], set()
    for s, rep, arm, i, acc, gi in positives(['R_fix']):
        if acc.get('origin') not in ('A_adm2', 'GUARD'):
            continue
        k = (s, i, acc.get('text') or '')
        if k in seen:
            continue
        seen.add(k); todo.append((s, i, acc, gi['label'], (J.get(k) or {}).get('judgement', {}).get('category')))
    print('todo', len(todo))
    live = Transport('mistral', MODEL, V6 / 'cache' / 'ground', max_calls=500, retry_failed=2, sender=paced)
    client = ReadThrough('mistral', MODEL, [], live=live)
    outp = V6 / 'ground_probe.jsonl'; outp.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()

    def one(t):
        s, i, acc, lab, cat = t
        if s not in rows:
            rows[s] = {r['id']: r for r in inputs(s)}
        rp = packet_for(rows[s][i], 20000)
        v = verify(client, rp, cand_of(acc, rp), MODEL, 0, 'verify_A', ARMS['R_fix'])
        with lock, open(outp, 'a', encoding='utf-8') as f:
            f.write(json.dumps(dict(set=s, id=i, label=lab, judge=cat, acc_text=acc.get('text'), status=v['verification_status'],
                                    raw=v.get('raw_verdict'), downgraded=v.get('downgraded'), analysis=(v.get('analysis') or '')[:400]),
                               ensure_ascii=False) + '\n')
    for s in {t[0] for t in todo}:
        rows[s] = {r['id']: r for r in inputs(s)}
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(one, todo))
    print(live.counts)


if __name__ == '__main__':
    main()

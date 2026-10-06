"""Layer H probe: checklist hypotheses -> shared verifier, per row; compare with label and R_fix decision.
usage: h_probe SET[,SET] [--only fn|neg|all] [--limit N]"""
import argparse, json, threading
from concurrent.futures import ThreadPoolExecutor
from guardian_truth.integrated import Transport
from guardian_truth.repair.clients import ReadThrough
from guardian_truth.repair import records
from guardian_truth.repair.v5 import ARMS, verify, decide
from guardian_truth.verification.pipeline import packet_for
from guardian_truth.v6 import checklist as H
from experiments.universal_repair.run import OUT, MODEL, inputs, paced
from experiments.universal_repair.score import gold_for

V6 = OUT.parent / 'guardian_v6'


def rfix(s, rep=1):
    ids = [r['id'] for r in inputs(s)]
    recs, _ = records.load(OUT / 'runs' / s / f'rep{rep}_R_fix_live.jsonl', ids)
    return {i: decide(r)[0] for i, r in recs.items()}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('sets'); ap.add_argument('--limit', type=int, default=10**6)
    ap.add_argument('--workers', type=int, default=3); ap.add_argument('--budget', type=int, default=40000)
    ap.add_argument('--out', default='h_probe.jsonl')
    a = ap.parse_args()
    live = Transport('mistral', MODEL, V6 / 'cache' / 'hlayer', max_calls=3000, retry_failed=2, sender=paced)
    client = ReadThrough('mistral', MODEL, [], live=live)
    outp = V6 / a.out; lock = threading.Lock()
    done = set()
    if outp.exists():
        done = {(j['set'], j['id']) for j in map(json.loads, outp.read_text().splitlines())}
    todo = []
    for s in a.sets.split(','):
        g, d = gold_for(s), rfix(s)
        rows = [r for r in inputs(s) if r['id'] in g][:a.limit]
        todo += [(s, r, g[r['id']]['label'], d.get(r['id'])) for r in rows if (s, r['id']) not in done]
    print('todo', len(todo), flush=True)

    def one(t):
        s, r, lab, dec = t
        try:
            p = packet_for(r, a.budget)
            h = H.run(client, MODEL, p, 0)
            vs = []
            for c in h['candidates'][:4]:
                v = verify(client, p, c, MODEL, 0, 'verify_H', ARMS['R_fix'])
                vs.append(dict(target=c['target_id'], req=c['requirement'][:300], reason=c['reason'][:300],
                               status=v['verification_status'], analysis=(v.get('analysis') or '')[:300]))
            j = dict(set=s, id=r['id'], label=lab, rfix=dec, adm=h['admission'], n_items=len(h['items']),
                     n_viol=sum(i['status'] == 'VIOLATED' for i in h['items']), n_cand=len(h['candidates']), ver=vs)
        except Exception as e:
            j = dict(set=s, id=r['id'], label=lab, rfix=dec, adm='EXC:' + repr(e)[:200], ver=[])
        with lock, open(outp, 'a', encoding='utf-8') as f:
            f.write(json.dumps(j, ensure_ascii=False) + '\n')
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, todo))
    print(live.counts, flush=True)


if __name__ == '__main__':
    main()

"""Layer C2 on stored v6 runs: A-owned 'missing confirmation' accusations with a code-checked affirmative reply are
re-reviewed once; the re-review decides. Writes outputs/guardian_v6/confirm_<sets>.jsonl (+ cache)."""
import argparse, json, threading
from concurrent.futures import ThreadPoolExecutor
from guardian_truth.integrated import Transport
from guardian_truth.repair.clients import ReadThrough
from guardian_truth.verification.pipeline import packet_for
from guardian_truth.v6 import confirm as C
from experiments.universal_repair.run import OUT, MODEL, inputs, paced

V6 = OUT.parent / 'guardian_v6'


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--sets', required=True); ap.add_argument('--out', default='confirm.jsonl')
    a = ap.parse_args()
    live = Transport('mistral', MODEL, V6 / 'cache' / 'confirm', max_calls=400, retry_failed=2, sender=paced)
    client = ReadThrough('mistral', MODEL, [], live=live)
    outp = V6 / a.out
    done = {(j['set'], j['rep'], j['id']) for j in map(json.loads, outp.read_text().splitlines())} if outp.exists() else set()
    todo = []
    for s in a.sets.split(','):
        rows = {r['id']: r for r in inputs(s)}
        for p in sorted((V6 / 'runs' / s).glob('rep*.jsonl')):
            for r in map(json.loads, p.read_text(encoding='utf-8').splitlines()):
                acc = r['accusation'] or {}
                if not r['v6'] or acc.get('certificate') != 'MODEL' or (s, p.stem, r['id']) in done:
                    continue
                fact = C.applies(packet_for(rows[r['id']], 400000), acc)
                if fact:
                    todo.append((s, p.stem, r, rows[r['id']], acc, fact))
    print('todo', len(todo), flush=True)
    lock = threading.Lock()

    def one(t):
        s, rep, r, row, acc, fact = t
        rp = packet_for(row, 20000)
        k = int(rep[3:])                     # same attempt index as the rep's A run would be wrong: use attempt 0 for all
        v = C.recheck(client, rp, acc.get('text'), fact, 'mistral', MODEL, attempt=0)
        with lock, open(outp, 'a', encoding='utf-8') as f:
            f.write(json.dumps(dict(set=s, rep=rep, id=r['id'], label=r['label'], fact=fact, acc=acc.get('text'), recheck=v), ensure_ascii=False) + '\n')
    with ThreadPoolExecutor(1) as ex:
        list(ex.map(one, todo))
    print(live.counts)


if __name__ == '__main__':
    main()

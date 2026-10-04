"""Phase 1: offline multi-packet coverage, nesting, overlap and integrity (zero inference).
Uses only cached first-pass replies for gap-directed packets (D2/G2/G4)."""
import json, sys, time
from guardian_truth.evidence_packer import PackerConfig, pack
from guardian_truth.multipacket import (Controller, complementary, gap_packet, oracle_packet, overlap_stats,
                                        reference_spans_covered, resolve_global, specialized, union_view, unify)
from guardian_truth.multipacket.packets import merge_records, reference_store
from experiments.multipacket_v1.common import OUT, baseline_reply, references, valid_gold, valid_rows
from experiments.multipacket_v1 import gaps


def ctrl_view(row, first, qs, order, hops, chars):
    c = Controller(row, first['selected_units'], order=order, max_hops=hops, max_chars=chars)
    c.explore(qs)
    units = [c.by[u] for u in c.selected]
    extra = dict(read_sources=merge_records(reference_store(row, units, []), units), current_targets=first['current_targets'],
                 declarations=first['declarations'], selected_units=list(c.selected))
    return extra, c.summary()


def main():
    refs, gold = references(), valid_gold()
    out = []
    t0 = time.time()
    for row in valid_rows():
        r = dict(id=row['id'], label=gold[row['id']]['label'], bytes=len(row['prompt'].encode()) + len(row['response'].encode()))
        A = pack(row, PackerConfig(budget_bytes=20000)); B = pack(row, PackerConfig(budget_bytes=48000))
        r['A_full'] = A['mode'] == 'FULL_INPUT'; r['B_full'] = B['mode'] == 'FULL_INPUT'
        sa, sb = set(A['selected_units']), set(B['selected_units'])
        r['nested_20k_in_48k'] = len(sa & sb) / len(sa) if sa else 1.0
        rep = (baseline_reply('U2_20k', row['id'], 1) or {}).get('admitted')
        views = {'A': [A], 'B': [B]}
        if not r['A_full']:
            P2 = complementary(row, A); views['C1/D1'] = [A, P2]
            N, E = specialized(row, 'NORM'), specialized(row, 'EVIDENCE'); views['C2'] = [N, E]
            G = gap_packet(row, A['selected_units'], gaps.d2_queries(rep)); views['D2'] = [A, G]
            G3 = gap_packet(row, set(A['selected_units']) | set(G['selected_units']), gaps.d2_queries(rep)); views['D3'] = [A, G, G3]
            for name, qs, order, hops, chars in (('G2_S', gaps.g2_questions(rep), 'PRIORITY', 4, 8000),
                                                 ('G2_L', gaps.g2_questions(rep), 'PRIORITY', 8, 16000),
                                                 ('G4_BFS_S', gaps.g4_questions(rep), 'BFS', 4, 8000),
                                                 ('G4_DFS_S', gaps.g4_questions(rep), 'DFS', 4, 8000),
                                                 ('G4_PRI_S', gaps.g4_questions(rep), 'PRIORITY', 4, 8000),
                                                 ('G4_PRI_L', gaps.g4_questions(rep), 'PRIORITY', 8, 16000)):
                extra, summ = ctrl_view(row, A, qs, order, hops, chars)
                views[name] = [A, extra]; r[f'{name}_ctrl'] = {k: summ[k] for k in ('hops', 'chars', 'stop', 'questions', 'loops_prevented')}
            for name, ps in views.items():
                if len(ps) > 1 and all('selected_units' in p for p in ps):
                    r[f'{name}_overlap'] = overlap_stats(row, ps)
        if row['id'] in refs:
            views['ORACLE'] = [oracle_packet(row, refs[row['id']])]
        for name, ps in views.items():
            full = [p for p in ps if 'source_sha256' in p]
            unified, _ = unify(row, ps if len(full) == len(ps) else [p if 'source_sha256' in p else dict(p, source_sha256=ps[0]['source_sha256']) for p in ps])
            resolve_global(unified, row)
            r[f'{name}_bytes'] = sum(len(json.dumps(p['read_sources'], ensure_ascii=False).encode()) for p in ps)
            if row['id'] in refs:
                r[f'{name}_cov'] = reference_spans_covered(refs[row['id']], union_view(ps))
        out.append(r)
    (OUT / 'offline').mkdir(parents=True, exist_ok=True)
    (OUT / 'offline/rows.json').write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print('rows', len(out), 'seconds', round(time.time() - t0, 1))
    summarize(out)


def summarize(out):
    print('A full-input rows:', sum(r['A_full'] for r in out), '| B full-input rows:', sum(r['B_full'] for r in out))
    nz = [r for r in out if not r['A_full']]
    print('rows needing retrieval at 20k:', len(nz), '| mean share of 20k units kept in 48k:',
          round(sum(r['nested_20k_in_48k'] for r in nz) / len(nz), 3), '| exactly nested:', sum(r['nested_20k_in_48k'] == 1 for r in nz))
    names = ['A', 'B', 'C1/D1', 'C2', 'D2', 'D3', 'G2_S', 'G2_L', 'G4_BFS_S', 'G4_DFS_S', 'G4_PRI_S', 'G4_PRI_L', 'ORACLE']
    ref = [r for r in out if 'A_cov' in r]
    for n in names:
        cov = [r.get(f'{n}_cov') or r['A_cov'] for r in ref]  # rows where A is full: every arm = A
        if n == 'ORACLE':
            cov = [r['ORACLE_cov'] for r in ref]
        if n == 'B':
            cov = [r['B_cov'] for r in ref]
        nf = sum(c['norm_found'] for c in cov); nr = sum(c['norm_required'] for c in cov)
        hf = sum(c['hist_found'] for c in cov); hr = sum(c['hist_required'] for c in cov)
        b = [r.get(f'{n}_bytes', r['A_bytes']) for r in nz]
        ov = [r[f'{n}_overlap'] for r in nz if f'{n}_overlap' in r]
        print(f"{n:9s} ref15 complete {sum(c['complete'] for c in cov):2d}/15  norm {nf}/{nr}  hist {hf}/{hr}  | mean read bytes(needs-retr) {sum(b)//len(b):6d}"
              + (f"  new units in later packets {sum(sum(o['new_units_per_packet'][1:]) for o in ov)/len(ov):.1f} repeated {sum(o['repeated_units'] for o in ov)/len(ov):.1f}" if ov else ''))


if __name__ == '__main__':
    main()

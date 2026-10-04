"""Why U2 20k beats U2 48k: per-row 3-run decisions, request identity, nesting and added content (zero inference)."""
import json
from collections import Counter
from guardian_truth.evidence_packer import PackerConfig, pack
from experiments.multipacket_v1.common import OUT, baseline_reply, references, valid_gold, valid_rows
from guardian_truth.multipacket import reference_spans_covered


def main():
    gold, refs = valid_gold(), references()
    man = json.loads((OUT.parent / 'evidence_packer_v2/llm/manifest.json').read_text())['entries']
    rows, summary = [], Counter()
    for row in valid_rows():
        i, y = row['id'], gold[row['id']]['label']
        dec = {arm: [(baseline_reply(arm, i, k)['admitted'] or {}).get('decision') for k in (1, 2, 3)] for arm in ('U2_20k', 'U2_48k', 'FULL')}
        correct = {arm: sum((d == 'ERROR') == bool(y) for d in ds) for arm, ds in dec.items()}
        same_as_full = man[f'U2_48k/{i}']['request_sha256'] == man[f'FULL/{i}']['request_sha256']
        A, B = pack(row, PackerConfig(budget_bytes=20000)), pack(row, PackerConfig(budget_bytes=48000))
        sa, sb = set(A['selected_units']), set(B['selected_units'])
        r = dict(id=i, label=y, a_full=A['mode'] == 'FULL_INPUT', b_same_as_full=same_as_full, dec=dec, correct_of3=correct,
                 a_units=len(sa), b_extra_units=len(sb - sa), a_kept_in_b=round(len(sa & sb) / len(sa), 3),
                 a_flips=len(set(dec['U2_20k'])) > 1, b_flips=len(set(dec['U2_48k'])) > 1,
                 b_extra_policy=sum(1 for r_ in B['read_sources'] if r_['category'] == 'POLICY') - sum(1 for r_ in A['read_sources'] if r_['category'] == 'POLICY'))
        if i in refs:
            ca, cb = reference_spans_covered(refs[i], A), reference_spans_covered(refs[i], B)
            r['new_required_norms_in_b'] = cb['norm_found'] - ca['norm_found']; r['new_required_hist_in_b'] = cb['hist_found'] - ca['hist_found']
        # categories (3-run consistency): stable = same correctness in >=2 of 3 runs for both
        if r['a_full']:
            cat = 'IDENTICAL_REQUEST_A_B_FULL' if same_as_full else 'A_FULL'
        elif correct['U2_20k'] >= 2 and correct['U2_48k'] <= 1:
            cat = 'A_RIGHT_B_WRONG'
        elif correct['U2_20k'] <= 1 and correct['U2_48k'] >= 2:
            cat = 'A_WRONG_B_RIGHT'
        elif correct['U2_20k'] <= 1 and correct['U2_48k'] <= 1:
            cat = 'BOTH_WRONG'
        else:
            cat = 'BOTH_RIGHT'
        r['category'] = cat; summary[cat] += 1
        rows.append(r)
    (OUT / 'reports/diag_20k_48k.json').write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    print(dict(summary))
    for cat in ('A_RIGHT_B_WRONG', 'A_WRONG_B_RIGHT'):
        sel = [r for r in rows if r['category'] == cat]
        print(cat, len(sel), 'labels', Counter(r['label'] for r in sel), 'B==FULL', sum(r['b_same_as_full'] for r in sel),
              'mean extra units', round(sum(r['b_extra_units'] for r in sel) / max(1, len(sel)), 1),
              'new req norms (ref rows)', [r.get('new_required_norms_in_b') for r in sel if 'new_required_norms_in_b' in r],
              'A-flips', sum(r['a_flips'] for r in sel), 'B-flips', sum(r['b_flips'] for r in sel))
        for r in sel:
            print('   ', r['id'][:40], 'y', r['label'], 'A', r['dec']['U2_20k'], 'B', r['dec']['U2_48k'], 'extra', r['b_extra_units'])
    nz = [r for r in rows if not r['a_full']]
    print('A-not-full rows', len(nz), 'A units fully kept in B:', sum(r['a_kept_in_b'] == 1 for r in nz), 'mean kept', round(sum(r['a_kept_in_b'] for r in nz) / len(nz), 3))
    # A vs B per error direction across all 3 runs
    for arm in ('U2_20k', 'U2_48k', 'FULL'):
        tp = sum(d == 'ERROR' for r in rows if r['label'] for d in r['dec'][arm]); fp = sum(d == 'ERROR' for r in rows if not r['label'] for d in r['dec'][arm])
        print(arm, 'ERROR on label1 (of 69)', tp, 'ERROR on label0 (of 69)', fp)


if __name__ == '__main__':
    main()

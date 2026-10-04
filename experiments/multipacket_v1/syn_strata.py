"""SYN-M1 strata (recall by operator / prompt size, FP rate) + whether the original (pre-mutation) value is inside the A packet. Zero inference."""
import json, collections, sys
from guardian_truth.evidence_packer.packer import pack, PackerConfig
from experiments.multipacket_v1.common import OUT
arms = sys.argv[1:] or ['A', 'B', 'FULL', 'CTRL', 'C1', 'D1', 'D2', 'G2_L', 'G4_S']
g = json.loads((OUT / 'suite_syn_m1/GOLD_eval_only.json').read_text())
rows = {json.loads(l)['id']: json.loads(l) for l in open(OUT / 'suite_syn_m1/inputs.jsonl')}
D = OUT / 'runs/syn_m1'
out = {'strata': {}, 'a_packet_coverage': {}}
dec = {a: collections.defaultdict(list) for a in arms}
for a in arms:
    for k in (1, 2, 3):
        for l in open(D / f'run{k}/{a}.jsonl'):
            r = json.loads(l); dec[a][r['id']].append(r['decision'] == 'ERROR')
for a in arms:
    c = collections.Counter()
    for i, x in g.items():
        for e in dec[a][i]:
            if x['label']:
                for grp in (x['operator'], 'gt20k' if x['prompt_bytes'] > 20000 else 'le20k'):
                    c[grp + '_n'] += 1; c[grp + '_tp'] += e
            else:
                c['neg_n'] += 1; c['neg_fp'] += e
    s = {k: round(c[k + '_tp'] / c[k + '_n'], 3) for k in ('FACT_NUMBER', 'CALL_ARG_ID', 'gt20k', 'le20k')}
    s['fp_rate'] = round(c['neg_fp'] / c['neg_n'], 3); out['strata'][a] = s
cov = collections.Counter()
for i, x in g.items():
    if not x['label']: continue
    p = pack(rows[i], PackerConfig(budget_bytes=20000))
    txt = json.dumps(p['read_sources']) if p['mode'] != 'FULL_INPUT' else rows[i]['prompt']
    cov[f"{x['operator']}|{'orig_value_in_A' if str(x['old']) in txt else 'orig_value_missing'}|A_detected_runs={sum(dec['A'][i])}"] += 1
out['a_packet_coverage'] = dict(sorted(cov.items()))
(OUT / 'reports/syn_m1_strata.json').write_text(json.dumps(out, indent=1)); print(json.dumps(out, indent=1))

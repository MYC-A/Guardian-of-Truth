"""R1 (programmatic reason checks) applied offline to frozen U2_20k / U2_48k replies on valid46. Zero inference."""
import json, collections
from guardian_truth.evidence_packer.packer import pack, PackerConfig
from guardian_truth.multipacket.ledger import programmatic_check
from experiments.multipacket_v1.common import valid_rows, valid_gold, baseline_reply, OUT

out = {}
gold = valid_gold()
for arm, budget in (('U2_20k', 20000), ('U2_48k', 48000)):
    c = collections.Counter(); flags = collections.Counter()
    for row in valid_rows():
        p = pack(row, PackerConfig(budget_bytes=budget))
        for run in (1, 2, 3):
            r = baseline_reply(arm, row['id'], run)
            if not r or not r.get('admitted'):
                continue
            rep = r['admitted']; f = programmatic_check(rep, p); y = gold[row['id']]['label']
            if rep['decision'] != 'ERROR':
                continue
            k = ('TP' if y else 'FP') + ('_pass' if f['r1_pass'] else '_fail')
            c[k] += 1
            for fl in ('target_valid', 'norms_exist', 'evidence_actor_ok', 'has_norm'):
                if not f[fl]: flags[f'{"TP" if y else "FP"}:{fl}=False'] += 1
            if f['historical_only_accusation']: flags[f'{"TP" if y else "FP"}:historical_only'] += 1
            if not f['cites_current_target']: flags[f'{"TP" if y else "FP"}:no_current_target_cite'] += 1
    out[arm] = dict(error_verdicts=dict(c), failing_flags=dict(flags),
                    note='if R1 failure vetoed ERROR -> FP removed = FP_fail, TP lost = TP_fail')
(OUT / 'reports/r1_offline.json').write_text(json.dumps(out, indent=1))
print(json.dumps(out, indent=1))

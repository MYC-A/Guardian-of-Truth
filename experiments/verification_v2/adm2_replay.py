"""Offline replay (no network) of the receipt-actor admission ablation on integrated-v1 valid46 runs:
frozen A2 (admission v1) vs admission v2, same cached replies (protocol §0 / summary §3.3)."""
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from guardian_truth.integrated import ReviewConfig, Transport, review
from guardian_truth.verification.admission import interpret_v2
from guardian_truth.verification.pipeline import packet_for

ROOT = Path(__file__).resolve().parents[2]


def main():
    d = pd.read_parquet(ROOT / 'valid.parquet')
    t = Transport('mistral', 'ministral-14b-2512', ROOT / 'outputs/integrated_v1/cache/mistral', offline=True)
    res = {}
    for rep in (1, 2, 3):
        cfg = ReviewConfig.profile('guard', budget_bytes=20000, attempt=rep - 1)
        cfg2 = ReviewConfig.profile('guard_adm2', budget_bytes=20000, attempt=rep - 1)   # end-to-end check of the profile
        rows = []
        for r in d.itertuples():
            a = review(r.prompt, r.response, cfg, client=t)
            s = a['steps'][0]
            v2 = interpret_v2(s.get('raw_content'), packet_for(dict(prompt=r.prompt, response=r.response), 20000))
            p1 = int(a['final_decision'] == 'ERROR')
            p2 = int(a['guard']['established_error'] or v2['decision'] == 'ERROR')
            b = review(r.prompt, r.response, cfg2, client=t)
            assert int(b['final_decision'] == 'ERROR') == p2, (r.id, b['final_decision'], p2)
            rows.append(dict(id=r.id, label=int(r.label), v1=s['admission'][:40], v2=v2['admission'][:40], d1=s.get('decision'), d2=v2['decision'], p1=p1, p2=p2))
        def f1(k):
            tp = sum(x[k] and x['label'] for x in rows); fp = sum(x[k] and not x['label'] for x in rows); fn = sum((not x[k]) and x['label'] for x in rows)
            return dict(tp=tp, fp=fp, F1=round(2 * tp / (2 * tp + fp + fn), 3))
        res[rep] = dict(profile_guard_adm2_matches_replay=True, v1=f1('p1'), v2=f1('p2'), rejected_v1=sum(x['v1'] != 'ADMITTED' for x in rows), rejected_v2=sum(x['v2'] != 'ADMITTED' for x in rows),
                        recovered=[(x['id'], x['d2'], x['label']) for x in rows if x['v1'] != 'ADMITTED' and x['v2'] == 'ADMITTED'])
    out = ROOT / 'outputs/verification_v2/reports/adm2_replay_valid46.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps(res, indent=1, ensure_ascii=False), t.counts)


if __name__ == '__main__':
    main()

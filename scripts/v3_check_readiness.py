"""Report unmet v3 data requirements; never silently relax training gates."""
import argparse
from collections import Counter
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--draft',type=Path,required=True)
    p.add_argument('--review-status',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    rows=[json.loads(line) for line in a.draft.read_bytes().splitlines()]
    review=json.loads(a.review_status.read_bytes());n=len(rows);positive=sum(r['label'] for r in rows)
    sources=Counter(r['source'] for r in rows);negative=n-positive
    checks=dict(size_15k_to_25k=15000<=n<=25000,
        positive_fraction_30_to_40=.30<=positive/max(1,n)<=.40,
        no_source_over_40_percent=bool(n) and max(sources.values())/n<=.40,
        hard_negatives_30_percent=sum(r['is_hard_negative'] for r in rows)>=.30*negative,
        real_long_inputs_20_percent=sum(r['n_tokens']>16384 for r in rows)>=.20*n,
        source_tau2_natural_and_pairs=any(r['source']=='tau2' for r in rows),
        near_and_id_checks=all(r.get('decontamination_status') for r in rows),
        required_label_audit_complete=bool(review.get('required_audit_complete')),
        disagreement_audit=bool(review.get('model_disagreement_audit_run')),
        human_holdout_frozen=bool(review.get('holdout_frozen') and review.get('holdout_human_reviewed')),
        paraphrase_human_reviews=review.get('paraphrase_human_reviews',0)>=100,
        group_scenario_splits=all(r.get('split') in ('train','dev','holdout') for r in rows))
    result=dict(schema='v3-data-readiness-v1',train_ready=all(checks.values()),checks=checks,
                rows=n,positives=positive,source_counts=dict(sources),human_reviews_completed=review.get('human_reviews_completed',0),
                corrected_label_fraction=None,reason='Unreviewed rows are not assumed correctly labelled',
                training_started=False,scope='Necessary checks only; passing is not sufficient without all B/C requirements')
    a.out.write_bytes((json.dumps(result,indent=2)+'\n').encode());print(json.dumps(result,indent=2))


if __name__=='__main__':main()

# V16: fixed final-checkpoint regressions, before V15 training

One final complete V15 checkpoint only, no epoch/threshold/model selection from
these results. Source remains the original frozen757 V7 regression inputs.
Fresh Rule/Evidence generation192 tokens, exact YES/NO, threshold0, UNKNOWN
preserves accusations, hard protection, no refill. Same source quote contract.
All these evaluation sets were previously inspected; EXPLORATORY.

Report fixed views: dev520 on the actual V10 full open/MAX pool.40;
real191 on historical overall-only pool.40 (explicitly not best-ZIP control);
valid46 on historical V5 best full MAX at BOTH .40 and .70. The .70 view is a
known safety regression, not a proposal to change production quota. Publish
TP/FP/FN/TN and removed FP / lost TP for every view. Do not hide an unchanged
or worse view by selecting another quota. No model error enters training.

Requires complete V15 quality run and idle GPU; finite own evaluation reserve.
If native data/training gates fail, skip and archive the failure. This check
does not satisfy original independent/human holdout or target-runtime gates and
cannot authorize production/ZIP. Do not call these repeated tasks independent.

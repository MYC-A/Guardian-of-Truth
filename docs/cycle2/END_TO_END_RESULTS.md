# Cycle 2 end-to-end results

## Protocol validity

The external source is `Alkur123/agentic-redteam-benchmark` pinned at commit
`12ddc82333e5df3581341493df4513a24cfc61bb`. The frozen sample contains 100
source-localized target steps from the source `gold` tier: 85 `ERROR` and 15
`NO_ERROR`. Selection did not use labels. Predictions were produced from
Guardian commit `025347018f979ec2e3356b89a937871a02c479f8` under the contract
frozen at `b98414a`; prediction SHA-256 is
`803d06282bf06bff775e05f61f07e6e4e15f129b34dddcfae05b12ce1ee20260`.

The source repository describes its gold tier as reviewed, but its machine
records contain no reviewer identifiers. This result is independently sourced
and step-localized, with that source-review provenance limitation stated rather
than silently upgraded.

## Main scores

| Arm | Reliability | Internal coverage | TP | FP | FN | TN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| X0 V5.3 | 1.00 | 1.00 | 0 | 0 | 85 | 15 | undefined | 0 | 0 |
| X1 holistic LLM | 0.02 | 0.02 | 2 | 0 | 83 | 15 | 1.00 | 0.0235 | 0.0460 |
| X4 VIGIL-like | 1.00 | 1.00 | 0 | 0 | 85 | 15 | undefined | 0 | 0 |
| X5_CORE | 1.00 | 0.00 | 0 | 0 | 85 | 15 | undefined | 0 | 0 |
| X5_PROTECTED | 1.00 | 0.00 | 0 | 0 | 85 | 15 | undefined | 0 | 0 |
| G1 exact formula | 1.00 | 1.00 | 0 | 0 | 85 | 15 | undefined | 0 | 0 |

For X5, schema reliability and semantic coverage are deliberately separate:
all executions were structurally valid, but all 100 solver states were
`UNRESOLVED`. Its binary adapter mapped those states to zero, producing 85
false negatives; this is not evidence of 100 safe decisions.

X1 made 100 sequential attempts with no retry. Two were valid and correctly
identified positive cases; one response was truncated and 97 requests failed
at the HTTP transport boundary after the provider stopped accepting the batch.
Thus its apparent precision and paired bootstrap interval over only two cases
do not establish model quality. Reported usage is 3,905 tokens for the two
completed calls; p50/p95 over all attempts are 1.16/15.17 seconds. Cost remains
`NOT_ESTABLISHED_PROVIDER_BILLING_NOT_AUDITED`.

## Paired comparisons

X4, X5_CORE, X5_PROTECTED, and G1 are identical to X0 on all 100 binary rows.
For each, McNemar has zero discordant cases and p=1; bootstrap 95% intervals for
delta F1, recall, and precision are all `[0, 0]`. No arm meets the predeclared
superiority requirement that the lower bound of delta-F1 be above zero.

X1 has only two jointly valid rows. It is correct where X0 is wrong on both,
but exact McNemar p=0.5 and 98 rows are unavailable. This is `NOT ESTABLISHED`,
not a model win or loss.

## Exact G1 result

The locked formula was evaluated unchanged:

`G1 = X0 OR (X4 AND X1)`

X0 has TP/FP 0/0; X1 has 2/0 on its valid subset; X4 has 0/0; `X4 AND X1`
has 0/0; G1 has 0/0. It adds zero TP and zero FP over X0. Because X4 returns
zero for every case, the formula short-circuits to zero without needing X1;
the 98 inherited X1 transport failures therefore do not change any G1 label.
The experimental G1 hypothesis is rejected on this holdout.

Detailed metrics, breakdowns, paired statistics, prediction records, and the
disagreement matrix are in `outputs/cycle2/e2e_results.json`,
`outputs/cycle2/external_predictions.json`, and
`outputs/cycle2/disagreement_matrix.json`.

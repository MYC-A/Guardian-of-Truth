# Coverage v2: budgeted facet cover (part 1)

Branch `research/coverage-v2-facet-cover-20261004`, based on
`research/retrieval-bakeoff-v1-20261004` (8e135f55). The frozen bakeoff code,
references and outputs are untouched; v2 is a new module plus its own harness.

## Why the bakeoff plateaued

Every arm is "rank units, take top-k". Diagnosis of misses at 80 KB showed the
failure is structural, not a ranking-quality issue:

1. **The read cap, not the bytes, was binding.** 9/15 inputs fit entirely in
   80 KB, yet top-k arms still read a subset and miss references.
2. **Conversation tail missed.** The latest user turn and the last diagnostic
   call/result (what the move directly answers) were absent in several cases.
3. **User utterances missed.** Consent, repeated requests and withdrawals are
   short user turns with little lexical overlap with the reply.
4. **Cross-lingual gap.** Russian replies vs. English policy; BM25 on the
   reply alone cannot reach the norm.
5. **Greedy stop.** Once facets saturate, a coverage greedy must keep filling.

## Method (`src/guardian_truth/coverage_v2/selector.py`)

Budgeted maximum coverage, `max sum_f w_f min(1, c_f(S)/need_f) s.t. bytes(S) <= B`,
solved by cost-benefit greedy. Facets come from the move only: literals
(ids, amounts, dates, codes, call operands), tool names, idf-weighted stems,
stems of the latest user turn, and pseudo-relevance feedback from journal units
that share move literals (this is the language bridge: reply -> tool JSON ->
policy). Phases with fixed a-priori shares:

0. whole input fits -> read everything (`mode=FULL_INPUT`);
1. conversation tail, newest first (15%);
2. user utterances, newest first (10%);
3. journal facet greedy, reserving the policy share;
4. policy whole if it fits 55% of the remaining budget, else facet greedy;
5. fill the remaining budget by unsaturated facet mass + recency.

Results pull their uniquely paired call. Every move literal gets a
GROUNDED/UNGROUNDED status over the whole prompt (a fabrication signal for the
verifier, never a verdict). `completeness_certified` stays false.
No case ids, labels, domain words or tool-specific rules.

## Results (frozen references and scorer, equal byte budget, read cap lifted for all arms)

| Budget | coverage_v2 dev / eval | best baseline dev / eval |
|---|---|---|
| 20 KB | 2/8 / 1/7 | local_bm25 2/8 / 3/7 |
| 40 KB | **6/8** / 2/7 | 3/8 / 3/7 (all arms) |
| 80 KB | **8/8 / 4/7** | 3/8 / 3/7 |

Only the cases that need real retrieval (input does not fit):
40 KB 4/11 vs 4/11 (tie), 80 KB **2/5 vs 0/5**.

Interpretation: most of the gain is architectural (read everything when it
fits, tail, user turns, fill). On hard long inputs it only ties at 40 KB. At
20 KB v2 is **worse** on policy (8/28 vs 19/28): the whole-policy rule cannot
fire and cross-lingual policy matching is still weak. Eval split is the same
known 15 cases, not a holdout. Reproduce:

```
PYTHONPATH=.:src python -m experiments.coverage_v2.evaluate outputs/coverage_v2
pytest -q tests/test_coverage_v2.py
```

## Next (part 2)

- Policy at small budgets: multilingual embeddings (e.g. `multilingual-e5-small`
  or BGE-M3) as an extra facet channel, not a replacement for literals.
- Long banking journals: entity-chain closure (literal -> all units holding
  it -> their literals, one hop) and latest-state per entity.
- New holdout from valid46 rows not in the 15, plus an LLM verdict A/B on packets.

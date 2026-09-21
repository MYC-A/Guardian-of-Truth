# FULL_21 Section 3+5: old Granite 8B modes, context length, and graph context

All runs: public46 (sha 9f6f5fc4...), granite-guardian-3.3-8b @ b3421eda,
temperature 0, think=false unless noted, transformers backend. Single changing
axis per row. Gold joined post-hoc. `no_score_token` cases are kept as
missing, never coerced to 0.

## Section 3 — context length (criterion groundedness, doc mode)

| Variant | TP | FP | FN | TN | F1 | OR-baseline F1 |
|---------|----|----|----|----|----|----------------|
| 6k | 17 | 6 | 6 | 17 | .7391 | .7917 |
| **12k (control)** | 16 | 2 | 7 | 21 | **.7805** | **.8889** |
| 24k | 15 | 1 | 8 | 22 | .7692 | .8837 |
| 60k (flash ref) | 10 | 0 | 13 | 23 | .6061 | .8780 |

Non-monotonic: 12k is the optimum among tested budgets. Shorter (6k) inflates
FP (17→6 FP); longer (24k/60k) loses recall monotonically. The frozen control
budget is genuinely near-optimal on this checkpoint — not an artifact.

## Section 3 — alternative officially supported criteria (@12k)

| Criterion | Input mode | TP | FP | FN | TN | F1 | OR-baseline F1 |
|-----------|-----------|----|----|----|----|----|----------------|
| answer_relevance | conv (last user turn + response) | 16 | 4 | 7 | 19 | .7442 | .8261 |
| evasiveness | conv | 4 | 0 | 19 | 23 | .2963 | .7222 |
| context_relevance | query_doc | 1 | 2 | 22 | 21 | .0769 | .6486 |

- answer_relevance is a near-peer of groundedness (same TP, +2 FP) with a
  DIFFERENT input contract — a genuine complementary risk mode.
- evasiveness: precision 1.0 (4 TP, 0 FP) — weak but pure; catches a
  disjoint failure class (non-engagement with policy guidance).
- context_relevance answers a different question (document utility), as
  expected — not useful for error detection here.

## Section 3 — think mode

First attempt (max_new_tokens=400): 17/46 cases produced no `<score>` token
(generation budget exhausted inside the reasoning trace). Honest coverage gap —
records preserved, missing kept missing. Rerun with max_new_tokens=1200:
see full21_s3_g12k_think_v2 (results appended below when complete).

## Section 5 — graph context (existing provenance graph, mechanical digest)

| Context | TP | FP | FN | TN | F1 | OR-baseline F1 |
|---------|----|----|----|----|----|----------------|
| bounded prompt @4800 (control) | 16 | 2 | 7 | 21 | .7805 | .8889 |
| graph digest only (~1.6-2.6k chars) | 19 | 21 | 4 | 2 | .6032 | .6032 |
| graph digest + original quotes | 15 | 5 | 8 | 18 | .6977 | .7826 |
| plain flat facts (no relations) | 16 | 16 | 7 | 7 | .5818 | .6316 |

**Honest negative result**: the structural graph digest as the primary judge's
document context makes Granite FP-heavy (21 FP). The digest surfaces
mismatches/unobserved arguments, and the checkpoint treats every surfaced
discrepancy as risk. Flat facts control shows the same FP inflation without
any graph relations — the problem is FACT-LIST CONTEXT per se, not graph
structure: graph_quotes (real text quotes present) is the least bad of the
three. This matches the previous session's negative gjudge result and the
directive's expectation: the graph's remaining promise is verifier-side
(per-suspicion evidence), not primary-judge context.

## Artifacts

- outputs/research_granite_guardian/full21_s3_{g6k,g24k,g12k_think,ansrel,evas,ctxrel}/
- outputs/research_granite_guardian/full21_s5_{graph,graph_quotes,plain_summary}/
- outputs/full21/s3s5_metrics.json, outputs/full21/s3s5_percase.csv
- runner: experiments/full21/run_granite_modes.py (byte-compatible scoring
  contract with control runner), experiments/full21/s5_graph_granite.py
  (digest via guardian_truth provenance, reused from superz_fullcycle/g_graph.py)

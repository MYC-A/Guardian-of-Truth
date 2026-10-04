# Semantic hybrid V4 results — 2026-10-04

The implemented lazy compiler and independent reverse discovery did not improve
final decisions. A contextual Gemma baseline produced useful decisions at lower
cost, but still made false accusations and interpreted missing information as
known. A general chronology filter improved the initial sample, then failed a
prospectively frozen counterexample. No new detector is promoted to production.

Source revision for the primary runtime is
`fd575bc29115680235b631e6339ca0903c0f63d1`, based on
`1980776e64190cdcd4017302b10f80d04b5ad735`. Reports, adapters and evaluation were
subsequent commits in `research/semantic-hybrid-v4-20261004`; exact normalized code
hashes, fixture hashes and model settings are in each `protocol.json`. Primary
seal: `93e2a55d35dcf3039cc1da499ce1ec5d8b679a977c85eda9efc0692da63e0435`.

## Primary same-model comparison

`ministral-14b-latest`, Mistral; temperature 0, bounded one-attempt HTTP client.
32 author-controlled cases: custody/reagent development, calendar/publishing
family holdout. All arms see original source policy and catalogue. A1's graph
protocol is unchanged; A2/A3 use code-issued IDs and delayed target-local formulas.
A3 sees original sources independently of forward discovery and unions candidates,
not verdicts. These changes are described in `ARCHITECTURE_CANDIDATES.md`.

HTTP 429 stopped the primary after 106 attempts. The saved 128 output records
include unavailable stages filled with UNKNOWN. Their nominal whole-file score
is not model accuracy on heldout inputs. The primary never reached an executed
heldout comparison. `execution_subset_metrics.json` reports availability separately.

| Arm | Executed supported cases | Correct 3-way | Decided | TP | False ERROR | Unavailable supported |
|---|---:|---:|---:|---:|---:|---:|
| A0 contextual | 14 | 5 | 13 | 3 | 8 | 18 |
| A1 original graph | 16 | 4 | 0 | 0 | 0 | 15 |
| A2 lazy lowering | 14 | 2 | 0 | 0 | 0 | 18 |
| A3 reverse + lazy | 13 | 2 | 0 | 0 | 0 | 19 |

A1 additionally excludes the single prose target. An executed schema/admission
failure remains in the denominator; an unreceived stage does not. For the 13
development cases with received stages in every arm, the fairer same-case table is:

| Arm | Correct / 13 | Decided | FP | FN | Unique requests | Known tokens | HTTP seconds sum |
|---|---:|---:|---:|---:|---:|---:|---:|
| A0 | 4 | 12 | 8 | 0 | 12 | 16,939 | 28.02 |
| A1 | 2 | 0 | 0 | 3 | 42 | 75,114 | 212.80 |
| A2 | 2 | 0 | 0 | 3 | 18 | 48,749 | 207.43 |
| A3 | 2 | 0 | 0 | 3 | 30 | 74,912 | 278.80 |

This interrupted, receipt-selected subset is exploratory, not a new sealed test.
A3 costs include its shared forward discovery dependency. Per-arm cache attribution
is not additive. A0 is better on 3-way accuracy and cheaper, but its eight false
ERROR decisions make it unsuitable as an automatic enforcement mechanism.

A2's 14 received outputs fail admission: five `FORMULA_CITES_NON_POLICY_SOURCE`,
nine `UNKNOWN_OR_DUPLICATE_WITNESS_PATH`. A3's 13 fully received outputs fail for
the same causes, five and eight. Thus the main end-to-end bottleneck is before
native formula evaluation; no quality gain can be attributed to a solver.

Saved discovery receipts select all gold-required source groups on 16 available
forward cases. Thirteen have nonempty received reverse discoveries; reverse adds
zero gold-required source IDs. Source-group selection does not measure correctness
of conjunction, exemption scope, modality, entity joins or completeness of norms.

## Development controls and provider-contract replication

| Phase / hypothesis | Mechanism and unchanged control | Data and result | Decision |
|---|---|---|---|
| Early graph fails mainly on addresses | Reuse existing IdGraph line spans and arity; original graph meaning/runtime | Dev only; one unique inventory admitted, but HTTP 429 interrupts all 16 full pipelines after 12 attempts | NEEDS_MORE_EVIDENCE for final accuracy; ID membership alone is not a semantic gain |
| A0 fails mainly on source roles | Code-owned ID enums in schema; same A0 prompt and Mistral | 15 received dev cases, 7 correct, 7 false ERROR; one unavailable; 429 stops phase | REJECT as sufficient semantic remedy |
| Primary failure is model-specific | Same strict wire, fixtures and A0/A2/A3 with Gemma 4 31B | 46 HTTP 200 receipts; provider ignores wire schema, emits fences/aliases; zero usable strict replies | Transport/schema replication failure, not semantic accuracy |
| Make output contract visible | Exact same schema in packet; strip at most one enclosing JSON fence; no value or formula repair | Two dev cases, A0 valid 2/2; A2 invalid 2/2 (`FORMULA_CITES_NON_POLICY_SOURCE`); 5 HTTP | KEEP provider adapter for this endpoint; compiler continuation fails its capability gate |

Each phase has its own pre-run seal and ledger. The last capability experiment
required at least 3/4 admissible outputs to continue the combined A0/A2 phase;
only 2/4 passed. A separately sealed contextual-only continuation follows that
observation without presenting it as a completed formal replication.

## Contextual Gemma continuation

Same original A0 prompt, input suite and gold, exact schema-in-packet adapter;
`gemma4:31b` through Ollama. 32 predictions from 31 unique successful requests
(one identical wire reused), 51,142 tokens. No schema/admission failures.

| Scope | Correct 3-way | Decided | TP | FP | FN | Binary F1, UNKNOWN→0 |
|---|---:|---:|---:|---:|---:|---:|
| All 32 | 25/32 (78.1%) | 31 | 7 | 3 | 0 | 0.8235 |
| Development | 12/16 | 16 | 3 | 2 | 0 | 0.7500 |
| Family heldout | 13/16 | 15 | 4 | 1 | 0 | 0.8889 |

All seven mistakes have gold UNKNOWN: three wrong-entity cases become ERROR;
three future-prerequisite cases become NO_ERROR; an opaque tool is imagined to
publish and becomes NO_ERROR. All seven explicit ERROR cases were found, including
the false-success prose claim. These small synthetic cases do not establish
general recall or a model-independent architectural win.

The broad effect label matches 30/32 gold labels; complete required-source group
selection is 14/23 eligible cases. Neither metric certifies interpretation.
No hand-annotated semantic NormRecall/ExceptionRecall result is claimed.

## Additional idea: temporal source guard and prospective falsification

Hypothesis: reject native evidence after the first target before trusting a
contextual verdict. Code uses existing graph positions and source IDs, makes no
new model call, and downgrades only to UNKNOWN. On the inspected 32 cases this
post-hoc diagnostic changes three chronology mistakes: 25/32 → 28/32; decided
coverage 31/32 → 28/32. It does not fix wrong-entity false accusations or opacity.

To test the apparent gain, freeze two new families before new inference: vault
prerequisite approval and quarantine immutable state (16 cases). Same model,
contextual prompt and schema adapter; gold/inputs and guard hash sealed in
`f1f58ce281fb5da50c1d424700d20e7bda5afd1b87cdd54b000271310ca5f867`.
Fixtures/protocol were pushed before inference. This is prospective but still
author-controlled, not externally blinded.

| Scope | Original correct | Guarded correct | Original TP/FP/FN | Guarded TP/FP/FN |
|---|---:|---:|---|---|
| New 16 | 11/16 | 10/16 | 4/3/0 | 3/3/1 |
| Vault 8 | 5/8 | 5/8 | 1/2/0 | 1/2/0 |
| Quarantine 8 | 6/8 | 5/8 | 3/1/0 | 2/1/1 |

The guard discards a lawful later reading of explicitly immutable classification,
losing a correct ERROR. It misses `vault.later` because the model mentions future
sources in prose but cites only the target ID. Reject the blanket guard for
promotion. Position checking must depend on whether evidence is an authorization
event or an observation of a stable state, with faithful structured witnesses.
16 successful new calls cost 20,427 tokens. No retrospective repair is substituted.

## Structural and historical verification

85 targeted tests pass: existing graph/quote/ranked-search/durable-worker/proof
tests and new experiment/guard tests. All seven V4 phases replay without HTTP,
with byte-identical predictions and unchanged HTTP ledgers. Historical graph
replay under Pydantic 2.10.3 also reproduces existing artifacts without HTTP.

The supplied-norm logic diagnostic examines 54 guard/condition/exemption assignments.
Six yield legacy UNKNOWN although the independent violation expression is FALSE.
This identifies over-abstention from irrelevant unresolved facts for one supplied
norm, not a fix for normative extraction or proof that a complete policy is safe.
Production evaluator behavior remains unchanged.

Historical System V2: full-auto universal 10/20 correct, 75% UNKNOWN; gold S1
17/20 correct; all-step oracle 19/20. Historical graph: both address arms 37/37
UNKNOWN. These are different inputs and historical disclosed evidence, not
comparative new heldout scores. See `BASELINES.md` and `FAILURE_ANALYSIS.md`.

Data and per-case explanations are in `outputs/searh_23/semantic_hybrid_v4*/`;
aggregate verification and comparison CSVs are in
`semantic_hybrid_v4_diagnostics_20261004/`. Reproduce with `RUNBOOK.md`.

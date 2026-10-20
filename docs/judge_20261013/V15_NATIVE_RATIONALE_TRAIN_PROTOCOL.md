# V15: native rationale SFT, frozen before optimization

Purpose: test replacing V7's short abstract workflows with source-native
explanations of applicability. Most of this is a different objective on existing
TRAIN data, not new independent data. No evaluation-derived examples or labels.

After V13 completes, consider source-audited native TRAIN pairs only. Exclude
turn-shape pairs handled by exact code and all pairs used in the 32-row frozen
BCE replay. Recheck each source constructor. Build Evidence solely from the
visible history and target: consent history, status, requested vs original
payment, available replacements, cabin/date eligibility, compensation request,
or observed factual values. Never use mutation dictionaries or future native
execution outputs in the explanation. Cite the original full governing clause.

Use unchanged production rendering plus the V7 Rule/Evidence question. Require
source-quote admission, exact tokenizer answer boundary, full untrimmed input,
and review <=176 tokens (reserve within deployed 192). Reject complete pairs on
failure. Select V13's bounded hard-pair order, maximum 64 pairs, round down to
four complete pairs per batch. Require at least 32 pairs; otherwise stop.
Add the 16 fixed V14 TRAIN role contrasts and the original 32 BCE replay rows.
Never add V14's four HOLDOUT rows. No duplicate IDs or partial effective batches.
All pair labels balanced. Source/proof checks remain bounded and human-unreviewed.

One fixed training arm, one full epoch: warm start original V5 35B adapter
eb7cee08c0a00c29ad1d21904aa94d29f4f83f126d53e1438dd65ef85a34ba4f,
last16 layers24--39, rank16 alpha32 dropout.05, LR2e-5 with two-update warmup,
AdamW weight_decay.01, effective batch8, seed20261020, clip1. Equal row weight;
rationale-token cross entropy plus BCE replay, as in V7. No LR/layer/epoch sweep,
no checkpoint selection by evaluation, no threshold change. CPU/gradient/memory
gates before updates; recoverable optimizer/RNG/order checkpoints each batch.
Time allocation for training: finite 3 hours after mining/data preparation,
with a separate evaluation reserve. A partial epoch is archived, never reported
as a completed arm or selected for quality promotion.

Evaluate complete final weights as another candidate-only verifier at the same
fixed threshold0, quota.40, hard protection and no refill. Use the frozen V12
1893-row control/pool and compare against BOTH base and previous V7 verifier.
All are exploratory; V12 was used by older 4B adapters. Report TP loss, FP removed,
admission and domain regressions, not only F1. The source-native tiny role holdout
can diagnose role binding but cannot establish whole-system acceptance.

No production or ZIP promotion. Do not promise private-score improvement. If
native data/gradient/runtime gates fail, preserve the failure and skip training
or downstream evaluation; do not fill from protected data or reset histories.

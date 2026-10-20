# Active research continuation, 20 October 2026

Snapshot after full V12 control completed; verifier arms still running.
No new private result, production promotion or ZIP is claimed. User authorizes
continued genuine improvement work without fitting evaluation data. The latest
GPU authorization is open; the finite allocations below are agent budgets,
not new user deadlines.

## Running dependency chain

1. `guardian-lab-v12-transfer-v1`:
   `/workspace/guardian-lab-20261018/v12-transfer-20261020/evaluation-v12`.
   Full best-profile overall/open/MAX control completed1893/1893 exact overall
   and final scores, without trimming/fallback; positive pool757, quota.40.
   Fresh base and frozen V7 LoRA candidate-only verifiers follow, threshold0,
   hard protection, no refill. Labels are joined only after both arms freeze.
   This cohort previously evaluated older4B adapters: EXPLORATORY, not pristine.
   Research eager/chunk64/extended time is not competition cold-start evidence.

2. `guardian-lab-v13-native-queue-v2`:
   `/workspace/guardian-lab-20261018/v13-native-mining-20261020`.
   Wait for complete V12 and idle GPU, then score1112 source-audited native TRAIN
   rows with the proper direct YES/NO verifier question. This is a mining proxy,
   not post-review deployment quality. Native receipt requirement excludes
   legacy rows without such receipts.556 complete pairs, maximum9885 input
   tokens. Only6 rows in this native subset are telecom; it lacks actor scope.
   Never use evaluation errors as training seeds.

3. `guardian-lab-v15-native-train-v3`:
   `/workspace/guardian-lab-20261018/v15-native-rationale-20261020-v3`.
   Currently waiting for mining. Build the frozen V15 recipe, require>=16
   selected native TRAIN correct twins with positive direct-mining scores,
   then at most one epoch, last16 layers, original V5 warm start. Joint loss:
   .5 rationale-token CE + .5 verdict BCE for SFT rows,32 frozen BCE replay rows.
   At most128 native SFT rows +16 new role rows +32 replay. Minimum64 native
   SFT rows. Pair/template caps, no duplicate IDs, no partial batches. No fill
   from protected data. If the gates fail, preserve FAIL and skip training.
   Training allocation<=3h with separate quality reserve; outer allocation5h.
   Evaluate complete final weights only, against the same frozen V12 pool and
   BOTH base and previous V7 verifier. No checkpoint/threshold selection.

The initial V13 prepared-v1/queue-v1 and V15 waiting-controller v1/v2 were
superseded BEFORE any mining/native optimization, with preserved receipts.
No native training calls occurred in those superseded controllers. Current V13
binary-question contract and V15 joint loss were frozen before mining scores.
Six deployed V15 code/protocol hashes match local bytes in
`CODE_FREEZE_BEFORE_TRAINING.json`.

## Data and technical evidence

V14 source-native role contrasts completed20 rows,16 TRAIN +4 reserved target
tool HOLDOUT rows in separate connected components. Native normal-mode routing
rejects assistant calls to user-owned tools; native solo mode allows direct
device reads. Correct guidance examples keep a tool mention separate from a
tool invocation. Full real policies and schemas, unchanged DB hashes, no future
execution result in model history/rationale. No reward-only labels, artificial
padding or evaluation dialogue seeds. New short constructed cases are not natural
trajectories. Two reserved tool groups are not independent-policy acceptance.

Offbox:1112/1112 native input text/token round trips passed with pinned
tokenizers0.22.2 and tokenizer SHA
`5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42`.
Actual primary Hugging Face token hashes also matched standalone tokenizer at
fixed positions0/946/1892 before the complete offbox replay.
All20 V14 row/parser/schema/source-quote predicates replayed locally; native
execution was not repeated offbox. Human review remains unavailable.

Pre-mining rationale preflight:868 eligible native rows /434 complete pairs,
12 families, no source-quote/budget/terminal-verdict rejection. This excludes
turn-shape cases handled by exact code. Evidence is computed only from visible
history/target, not mutation dictionaries, labels or future execution receipts.
Native source repetition is a new objective on existing data, not new tasks.
V15 changes both data and decision loss: a gain cannot be attributed to either
factor separately without another experiment.

Data exported and SHA verified offbox:

- `A:/Guardian-submissions/guardian-v13-native-mining-20261020/prepared-v2-export.tar.gz`:
  `eb68b6f8e6b910ff230a390d1c49ca403f4d7b7d2c1ca5c42aa21a7c7843cba6`.
- `A:/Guardian-submissions/guardian-v14-native-role-data-20261020/data-v1-export.tar.gz`:
  `1fc6371d0d8a9fa16a4fcf9b23fd3c40e360a704bfb6ddb6dcc7cb9d27a43788`.

Aggregate evidence: `v13_v14_evidence/OFFBOX_PREPARATION_AUDIT.json`.
Protected histories, labels and model output blobs stay off Git.

## Supervision and recovery

Finite Windows collectors sync V12, V13 and V15-v3 archives to corresponding
`A:/Guardian-submissions/guardian-v*-20261020*` directories. They verify archive
size/SHA after copying. V15 exports full optimizer/RNG/order with the final
checkpoint, or the last complete checkpoint if training fails. No resets of a
committed run. Failed/partial runs remain explicit, not successful quality arms.

Independent V12 offbox replay: `scripts/v12_offbox_report.py`, using the pinned
tokenizer and saved primary inputs. Reconstruct MAX quota, every verifier input
and admitted final-token sequence, actual generation-input receipts, source
admission, GPU A/B tensor proof and all metrics. Raw model logits are not in the
archive; exact odds rely on the checked producer contract. No absolute/private
improvement or original acceptance follows from these exploratory checks.

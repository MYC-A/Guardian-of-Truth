# Active research continuation, 20 October 2026

Snapshot: V12 complete and independently audited offbox; V13 TRAIN mining done.
V15 failed its original error-count gate; V17 limited recipe preparing to train.
No new private result, production promotion or ZIP is claimed. User authorizes
continued genuine improvement work without fitting evaluation data. The latest
GPU authorization is now limited by the user's latest instruction to one,
possibly two hours. The v4 total deadline is recorded locally in
`artifacts/v15/ALLOCATION_V4.json`; no automatic extension.

## Running dependency chain

1. `guardian-lab-v12-transfer-v1`:
   `/workspace/guardian-lab-20261018/v12-transfer-20261020/evaluation-v12`.
   Full best-profile overall/open/MAX control completed1893/1893 exact overall
   and final scores, without trimming/fallback; positive pool757, quota.40.
   Fresh base and frozen V7 LoRA candidate-only verifiers completed, threshold0,
   hard protection, no refill. Labels are joined only after both arms freeze.
   This cohort previously evaluated older4B adapters: EXPLORATORY, not pristine.
   Research eager/chunk64/extended time is not competition cold-start evidence.
   F1: control .676692, base verifier .692308 (30 FP removed, no TP loss),
   previous V7 LoRA .687692 (27 FP removed, three TP lost). See
   `V12_TRANSFER_RESULTS.md`. These outcomes do not change the frozen V15 recipe.

2. `guardian-lab-v13-native-queue-v2`:
   `/workspace/guardian-lab-20261018/v13-native-mining-20261020`.
   V12 dependency passed; scored1112 source-audited native TRAIN
   rows with the proper direct YES/NO verifier question. This is a mining proxy,
   not post-review deployment quality. Native receipt requirement excludes
   legacy rows without such receipts.556 complete pairs, maximum9885 input
   tokens. Only6 rows in this native subset are telecom; it lacks actor scope.
   Never use evaluation errors as training seeds.
   Result:12 TRAIN proxy FP,65 FN; bounded selection182 rows,8 FP. All12 FP
   are airline cancellation/compensation. Original V15 >=16-error gate fails.

3. `guardian-lab-v15-native-train-v4`:
   `/workspace/guardian-lab-20261018/v15-native-rationale-20261020-v4`.
   Stopped before optimization after original gate failed. Original recipe: require>=16
   selected native TRAIN correct twins with positive direct-mining scores,
   then at most one epoch, last16 layers, original V5 warm start. Joint loss:
   .5 rationale-token CE + .5 verdict BCE for SFT rows,32 frozen BCE replay rows.
   At most128 native SFT rows +16 new role rows +32 replay. Minimum64 native
   SFT rows. Pair/template caps, no duplicate IDs, no partial batches. No fill
   from protected data. If the gates fail, preserve FAIL and skip training.
   Training maximum5400 seconds; total remaining allocation7200 seconds with
   quality reserve900 seconds. See `V15_TWO_HOUR_BUDGET_AMENDMENT.md`.
   Evaluate complete final weights only, against the same frozen V12 pool and
   BOTH base and previous V7 verifier. No checkpoint/threshold selection.

4. `guardian-lab-v17-native-budget-v1`:
   `/workspace/guardian-lab-20261018/v17-native-budget-20261020-v1`.
   Explicit separate limited experiment, not a passed V15 gate. Frozen before
   optimization in `V17_BUDGET_NATIVE_TRAIN_PROTOCOL.md`. Exactly32 native
   pairs (64 rows),16 role rows,32 BCE replay =112 rows /14 updates /one epoch.
   Stable-prioritize bounded TRAIN false-accusation pairs, then original
   round-robin order. At least8 actual TRAIN proxy errors, two native domains.
   Original source/isolation/quote/token/gradient checks retained. Same warm
   start,16 layers, joint objective, final-only evaluation. No external-error
   training. SAME two-hour absolute deadline, 19:11:35 MSK, no clock reset.

5. `guardian-lab-v16-final-regressions-v4`:
   `/workspace/guardian-lab-20261018/v16-final-regressions-20261020-v4/evaluation-v16`.
   Wait for V17 complete final weights; score dev520/real191/valid46 with the
   original fixed views, including valid46 .40 and .70. Same absolute deadline
   as v4; skip if insufficient reserve. No quality-feedback training.

The initial V13 prepared-v1/queue-v1 and V15 waiting-controller v1/v2/v3 were
superseded BEFORE any mining/native optimization, with preserved receipts.
No native training calls occurred in those superseded controllers. Current V13
binary-question contract and V15 joint loss were frozen before mining scores.
Six deployed V15 code/protocol hashes match local bytes in
`CODE_FREEZE_BEFORE_TRAINING.json`.
V16 v2 failed before inference because its copied code snapshot lacked its
protocol document. Preserved FAIL; v3 includes the document. No GPU quality
retry, threshold or data change.

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

Finite Windows collectors sync V12, V13, V17-v1 and V16-v4 archives to corresponding
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

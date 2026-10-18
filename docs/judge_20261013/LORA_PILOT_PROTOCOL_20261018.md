# LoRA judge pilot v1 — frozen before training, 18 October 2026

Authorized small offline learning experiment, not a submission change. No private
test is available. Do not promise a target F1 from synthetic controls or papers.

Base: Qwen/Qwen3-4B-Instruct-2507, revision
cdbee75f17c01a7cc42f958dc650907174af0554; pin and verify every downloaded file.
BF16 Transformers, SDPA, one A6000. PEFT0.21.2 / accelerate1.15.0 in our own venv;
existing torch/transformers retained. Public model card:
https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507
Adapter API: https://huggingface.co/docs/peft/main/package_reference/lora

Data: only the old Compli technical PILOT partition is reclassified as training.
Its3 intent families remain disjoint from dev520/eval1893. All24 previously used
technical conversations are training only. Five other conversations, selected by
fixed hash without labels/scores, provide41 validation turns. Of259 possible
training prefixes,13 exact validation-prompt collisions are purged;246 natural
prefix examples train. Upstream synthetic gold and task adaptation limits
remain explicit. No train example comes from dev520, eval1893, seen397 or valid46;
exact prompt/pair overlap checks include all protected inputs. Family separation
uses the existing near-dialogue grouping; this is not a proof of semantic independence.

Add280 controlled whole-turn cases (5domains, scenarios1..4,14variants) and140
authorization cases (same domains/scenarios1..2). Authorization targets deliberately
remain YES when only eligibility becomes false, while whole-turn targets become
violation YES. Training total666:526 whole-turn+140 authorization. Templated cases
are an experimental supplement, not a complete training release. Fitness/clinic
scenarios8..15 are domain-disjoint synthetic diagnostics; still templated, not
fresh competition data. Separate training inputs from evaluation gold sidecars.

Objective: binary next-token answer-group log odds, differentiable logsumexp over
the existing one-token YES/NO aliases. This matches our exact inference scores;
it is a classification LoRA pilot, not a reproduction of a paper's generative
SFT/CoT recipe. Whole-turn and authorization prompts remain separate tasks.
All backbone parameters frozen; only LoRA trained. Rank16, alpha32, dropout.05,
all-linear targets, AdamW lr1e-4, weight_decay.01, clip_norm1,5 optimizer steps
linear warmup, then fixed LR. One shuffled epoch, seed20261018, effective batch16,
microbatch1, gradient checkpointing. No checkpoint/hyperparameter selection by gold.
Training input cap8192: drop over-cap rows without inspecting labels; never trim
policy/history to make them fit, report all exclusions. Evaluation cap16384; any
missing evaluation coverage blocks quality promotion. No synthetic generation API.

Evaluate fixed base and final adapter on the SAME exact rendered inputs:41 natural
validation,448 synthetic whole-turn/authorization diagnostics,520 protected dev
examples. Log full input/token hashes and finite full-vocabulary answer-group
scores; no generated-label parser. Store base scores before optimization, adapter
scores after it. Evaluation inference reads no gold. Gold-reading analysis is separate.
Also compare fixed mean of percentile ranks of saved35B overall and each4B scorer;
do not fit a weight or search a threshold. Main quota .40; .30 and zero-logodds
are secondary diagnostics. Dev is already inspected, hence EXPLORATORY.

Screen for a larger run only if full dev coverage, adapted dev F1@.40 exceeds base
by at least .02, AUROC improves by at least .01, and adapter or its fixed ensemble
reaches saved35B overall dev F1 .600567. Failure stops v1 after this pilot. Passing
only justifies a later broader comparison; it is not acceptance or a hidden-test
prediction. eval1893 remains untouched in this pilot, and seen397/valid46 do not
train. Finite supervised job bound2h; preserve partial receipts on technical failure.
Stop for repeated technical failure or nonfinite loss, not after seeing a desired
evaluation score. Save and hash the adapter off the GPU host before publication.

Quota sensitivity is a separate CPU replay on saved scores (.20 through .80).
It does not train/select this adapter and is not permission to claim a better
private-test score. In particular, raising .40 to .50 helps seen397/valid46 but
hurts dev520; distributions differ. No automatic submission is authorized here.

Technical revision v1b BEFORE OPTIMIZATION: v1a was stopped with589 base-only
scores and0 training steps when an additional within-partition exact-prefix check
found4 duplicate pairs and5 duplicate prompts between training and validation.
The thirteen colliding training rows are dropped without reading evaluation
quality. All evaluation inputs and optimizer settings remain fixed. v1a partial
receipts are preserved and excluded from quality analysis; v1b starts fresh.

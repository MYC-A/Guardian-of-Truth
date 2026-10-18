# Frozen C/E hours experiment, before new optimization/evaluation

Fresh pinned Qwen3-4B-Instruct-2507 (cdbee75...), no v1/v2 adapter continuation.
L1 binary cross entropy on exact sum YES vs NO next-token masses, same production
render and answer token mapping as base. LoRA r16/alpha32/dropout.05/all-linear,
AdamW lr1e-4 weight_decay.01, clip1, warmup first5 updates, effective batch16,
microbatch1, bf16, SDPA, nonreentrant gradient checkpointing, seed20261019.
Initial candidate one epoch. Save intermediate checkpoints every20 updates;
if time budget interrupts an epoch report partial, never silently call it complete.

Technical pilot: ten longest actual candidate inputs, forward/backward only,
discard pilot adapter. No quality/evaluation scores select training data or length.
Try full cap32768, if memory fails try24576 as original request allows. Overcap
rows excluded with counts, never silently truncated. Measure throughput, choose
source/family/group-stratified rows by stable hash and token budget with20% time
reserved for evaluation/backup. Record selected data hashes BEFORE training.
Compare optional second epoch/L2 only if measured remaining time permits; L1
checkpoint choice only independent DEV, no protected eval/holdout tuning.

Dataset replacement: ToolACE Apache2 pinned6bda777... is an additional source,
not CompliBench guideline generation. Preserve original source prompt and calls;
missing-parameter and unavailable-tool refusals may be negative only after audit.
Paired source-result factual/argument perturbations must have mechanically valid
evidence, retain entire original history before target, no future outputs.
Native instructions contain an internal function-call-vs-text inconsistency:
do not treat every upstream response as gold correct without resolving scope.

Official tau2 simulations bind BOTH agents/users to local endpoint, cache off,
auto-review off, ENV evaluator only. Three sequential configurations4B/8B/35B,
three stable-hash taskIDs/domain, two seeds initial bounded series (54 attempted
trajectories). Telecom only DEV. All model/seed variants of a task in same group.
Natural trajectory success is not sufficient proof of target-turn correctness;
label only source-supported turns, drop ambiguous/after-first-error, preserve
failed/truncated trajectories. Synthetic rule-conditioned cases must be marked
perturbation and never called natural trajectories or independent human labels.

Decontaminate against protected input-only sets before split. Scenario/pair/entity/
near components grouped. Holdout frozen before training, HUMAN_UNVERIFIED, no
evaluation-driven changes. Human review unavailable, original ACCEPT gate unmet.
Machine-complete experiment status EXPLORATORY_ONLY even if metrics improve.

E: same frozen R0 .40 and hard override; report standalone base/adapter and any
frozen production blend separately. AUROC/AP, precision/recall/F1, matched-recall
FP change and grouped bootstrap95% CIs, valid46 subset of397, real191 subset
reported distinctly. No tuning on those evaluations. Veto only if semantic
prerequisites demonstrated; UNKNOWN keeps label, citation match alone insufficient.
No invented held-out acceptance; retain original E/F thresholds and runtime
requirements. If anything fails do not assemble ZIP or alter production.

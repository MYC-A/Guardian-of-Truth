# Tool-truth LoRA v2: fixed experiment before optimization — 18.10.2026

Objective: improve the actual contest judge. The current reported platform F1
is .4585; local regression F1 is not a substitute. One adapter experiment,
no threshold search or repeated checkpoint selection. Qwen3.6-35B remains the
production reference. No automatic submission or production change.

Data: official tau2-bench revision96a3ef92329baf908ffe9dfe188cea34e8701d2a,
archive SHA256 c19fb4293a0565bd955dc2bc9388ae7ad30ffcc51f597388070aacfa09329ae7.
Policies, actual entity records and tool signatures are read as data/source;
external code is not executed. Constructed histories are NOT naturally annotated
trajectories. Cancellation-result snapshots follow the read source tool behavior,
but no tool was actually executed. Source records and policy/catalog are retained.

666 training examples: exact same246 natural Compli rows from v1, replacing all420
old synthetic/authorization examples with420 whole-turn controlled contrasts.
Two source domains, seven families,15 source users per domain, two targets per
family. Families: factual value, unsupported tool argument, completion without
result, eligibility/false escalation, consent in history, earlier-error scope,
unsupported facts in a valid transfer's summary. Positive and negative contrast
members stay together. This changes both data and task mix, not a pure ablation
isolating one failure mechanism. No evaluation row or label becomes training.

Entity selection uses deterministic source hashes, without model results. Exclude
source user IDs and selected resource IDs appearing in protected historical input.
Validation: six different source users per domain,168 controlled examples sharing
templates, plus previous41 natural validation. Check source hashes, groups,
exact protected pairs and train/validation prompt overlap. Source/user exclusion
is not a proof of semantic independence. Independent audit code checks588 targets
against parsed calls/results and records; same author, no independent annotator.
No gold field/oracle reaches an evaluation model prompt.

Diagnostic35B overall pass on all588 new inputs, input-only; no generative review.
Keep validation scores blinded until the v2 checkpoint is frozen. Inspect training
errors against source rules before optimization to detect label defects. No
automatic relabeling to agree with the model and no tuning to validation. This
pass is diagnostic, not a new residual architecture or a sampling rule. No hints
in these synthetic inputs; report this difference from saved hinted35B references.

Train fresh Qwen3-4B-Instruct-2507 base pinned at cdbee75f17c01a7cc42f958dc650907174af0554;
do not continue v1. Identical one-epoch seed20261018, rank16/alpha32/dropout.05,
all-linear, BCE on full-vocabulary YES/NO alias-group log odds, AdamW lr1e-4,
weight_decay.01, effective batch16/micro1, warmup5, clip1,42 optimizer steps.
BF16/SDPA/checkpointing; backbone frozen; train input cap8192, no trimming or
silent exclusions: any over-cap row stops the run before optimization. Evaluation
cap98304, no trimming. Preserve every failure and partial receipt. Bound each
supervised job; do not alter drivers or other services.

Paired base/v2 on209 diagnostic examples; v2-only full397 Guardian inputs joined
to hash-identical existing base/v1 receipts locally. Report real191 separately
from authored lockboxes and valid46, with all-YES baseline, AUROC/AP, zero-boundary
and fixed quotas.30/.40/.50/.60, TP gained/lost, FP removed/added. Same fixed
equal-percentile-rank ensemble with35B overall as v1; no fit of weights. AUC and
FP at matched recall are primary diagnostics; high-prevalence F1 is not a hidden
test prediction. Never count valid46 again as independent data.

Further candidate work requires complete finite coverage, real191 AUROC improvement
over v1 .830780 and valid46 AUROC not below base .937618 by more than.02, with
valid46 F1@.40 at least .809268. Compare against35B overall, not only small base.
Failing a gate rejects promotion, not all future training. Passing only permits
fresh target-like validation and a full target-runtime test before a controlled
platform trial. Explicitly report if a veto/ensemble loses genuine detections.
No production readiness or F1 .6+ claim follows from this protocol.

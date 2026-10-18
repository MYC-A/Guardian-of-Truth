# Frozen LoRA transfer check — 18 October 2026

The one-epoch adapter passed the preregistered small-pilot screen. Freeze it now:
adapter_model.safetensors SHA256
7e14c036d15d112e52433d2e4ad970ef0b9c9bda956c546eb3bcc06c2813d1b5.
No additional optimization, data generation, checkpoint selection or tuning.

Next inference only: all1893 previously unused Compli eval prefixes, then all397
seen real Guardian cases, both frozen base4B and adapter, identical full inputs.
valid46 is matched as a subset of397, preserving its own quota calculation/order;
not an independent dataset and no double counting. No evaluation gold is loaded
on GPU. No old35B scores or notes enter the4B prompts. Use existing full judge
system and user renderer, no hints, no truncation, BF16/SDPA/microbatch1,
logits_to_keep1, full-vocabulary YES/NO alias-group log odds. Use original base
tokenizer to retain exact pilot prompt contract; base and adapter see same inputs.
Input cap98304: explicit over-cap failures block full coverage claims; never trim
silently. Log input/source/token identities and walltimes. Bound job3600s.

Evaluation reads gold in a separate local analyzer. Report quotas .30/.40/.50/.60,
fixed zero-logodds diagnostic, AUROC/AP, counts and paired conversation/group
uncertainty where provenance supports it. Real397 remains SEEN and its class
balance differs from platform; fresh1893 gives external family-separated
evidence, not Guardian hidden-test performance. Apply saved structural hard
positives to real quota comparisons; show their count. For Compli there are no
hard tool-call positives. Compare reference35B overall/final on the same real IDs.
Do not retune an ensemble or accept a new threshold based on this run.

Gate to further deployment work: complete finite scores for all2290 pairs in
both arms; fresh eval1893 F1@.40 and AUROC improve over base, and seen397 adapted
F1@.40 does not fall below base by more than .02. Failing real transfer prevents
universal judge promotion, even if Compli gains are large. Passing is still no
evidence of contest runtime or hidden F1. Full archive/weights remain unchanged.
All results and failures are published; no repeat until a new issue justifies it.

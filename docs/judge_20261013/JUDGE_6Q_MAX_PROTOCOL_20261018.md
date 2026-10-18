# 6q available maximum — 18.10.2026

User rejected the all-six-or-overall gate, and then rejected a complete-question gate:
a useful score on one row must survive missing scores elsewhere. This explicitly
supersedes the strict all-or-nothing requirement for this opt-in profile.
Base: 33c0eb5ac55941d775e0e8bdefda8fa4adb57701. No new GPU quality results have been viewed.

One fixed candidate: JUDGE_6Q_MAX.json, legacy, six unchanged questions @on,
review off, aggregate=max_logit, per_chunk, chunk16. For every row use
max of the available finite exact log P(YES)-log P(NO) from the six keys.
No global complete-row or complete-question requirement; no averaging away
a larger error score with negative answers to unrelated narrow questions.
Missing/inexact/error/bounded are absent, not NO or zero. Negative-only rows
retain their negative maximum. No valid score means existing technical fallback.
The .30 quota and mechanical hard override remain unchanged. No row is forced
positive just because a model score is positive; ranking is still used.

This is a different, untrained rule, not a proven calibrated ensemble. All keys
use YES=violation, but question-dependent calibration can differ. Max can amplify
one false positive; more observed questions create more chances for extreme noise.
Incomplete scoring may correlate with length/group/order. No quality improvement
or equivalence of scales is claimed. No new thresholds, weights, LoRA/models,
blind, shuffle, preprocessing fit, result cache or class-prevalence adjustment.
tool_use covers performed calls, not every missing obligation.

Same pinned model/revision/runtime/limits as the preceding 6q build:
cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit @ 00fcea2d3bcf5389b518d4fc082e5590e0ba4844;
Python3.12.3/vLLM0.19.1/Torch2.10.0+cu128/Triton3.6.0/Transformers5.8.0.
Window49152, sequences64, batched_tokens16384, memory.90, prefix caching/chunked
prefill enabled. Exact one-token scoring at T1.0. Stop1380/kill1530/watchdog1680
from predict;1800 external includes startup. No measured GPU timing available.

Reuse existing primary-durable/per_chunk/deadline-aware extras. All completed
extra results are consumed immediately on file updates, independent of other
rows/questions; malformed later work preserves prior records. Primary still has
priority, so extras may never run. A sole overall score naturally remains itself.
New ranked_rows/ranked_coverage and per-key coverage expose available ranking data.
Old mean_z/max_z/logistic profiles retain their strict completeness behavior.

Technical gates: finite/inexact/missing/negative-only tests, a single positive
extra on only one row changes exported ranking, missing other columns/rows does
not revert it, old strict profile unchanged, gold/id isolation, actual eval uses
the same max rule, real-tokenizer caps, Linux CI and full ZIP integrity/import
closure/pinned weights/runtime. Fake-vLLM proves wiring only, not quality/speed.

GPU_UNTESTED: no new independent data inventory/splits, real model F1/AUC/AP/CI,
coverage/cache/VRAM or whole-script timing. No new SSH attempts: two configured
endpoints already timed out/refused this session. Quality verdict remains
INSUFFICIENT_EVIDENCE. Technical correctness does not guarantee a different platform score.

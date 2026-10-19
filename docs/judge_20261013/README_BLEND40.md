# Guardian 35B + Qwen4B/LoRA V4 — experimental submission

Run: `python scripts/predict.py --input test.parquet --output predictions.parquet`.
Output preserves input order and literal IDs, including duplicates; columns id,label.
No internet or training data is required at inference. All weights are bundled.

Two GPU processes run sequentially:
1. Qwen3-4B-Instruct-2507 with the fixed V4 LoRA, exact YES/NO scores, source only.
2. Qwen3.6-35B-A3B AWQ with overall -> open answer audit -> exact final.
   Its per-row score is max(available finite exact overall, final).
3. With complete N/N exact coverage of BOTH scorers, average their percentile
   midranks 50:50. Apply the .40 quota with the mechanical hard override.
   Otherwise use the entire available 35B ranking; missing scores are not NO.

Parser/source-boundary fixes and bounded turn-shape checks are enabled. An
unresolved policy exception never authorizes an added turn-shape accusation.
The hard override can exceed .40; .40 is a ranked share, not a probability.
The LoRA is for the 4B model; it is not attached to the 35B model.

Budgets from entrypoint start: auxiliary up to240s; primary stop1560s;
GPU process kill1680s; watchdog1740s. Durable mechanical/35B outputs survive
auxiliary errors or incomplete coverage. CPU and archive checks alone do not
prove a full private test will finish within the external1800s limit.

Research status: strong gains on constructed HUMAN_UNVERIFIED V4 DEV/HOLDOUT,
no improvement on valid46, mixed results on other explored cohorts. This is
an experimental candidate; no private-test gain or top-ranking claim is made.
See the accompanying release receipt for GPU coverage/time and final ZIP SHA.

Pinned weights and adapter identities are in JUDGE_MANIFEST.json; all archive
members, sizes, hashes and executable modes are in MANIFEST.json.

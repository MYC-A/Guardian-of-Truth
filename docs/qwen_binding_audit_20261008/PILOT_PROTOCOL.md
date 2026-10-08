# Frozen diagnostic: value-blind vs visible argument binding

Registered before inference on 2026-10-08. Goal: improve Qwen B2 through
source-grounded entity/argument selection, without benchmark-specific rules.
This is a development experiment, not a new independent holdout.

## Hypothesis and matched intervention

Hiding the actually used argument values may reduce anchoring to the current
assistant's choice. A model independently selects expected source leaves from
original user constraints and native receipts; code compares typed values.
The visible control has the same task, schema, sources, output limit and
verification protocol. Its additional input is the actual argument value.
Both modes hide current prose. Sources are a full production-parser packet;
this controls presentation-level blindness, not arbitrary upstream retrieval.

A code mismatch is only source support. A separate full-packet model check
tests policy applicability, correct entity/field role, allowed alternatives,
lawful attribute edits, stale/failed results, explicit user revisions and
exceptions. Exact policy/evidence citations are admitted separately. A
SUPPORTED verdict remains **model authority**, never a mechanical certificate.

## Fixed inputs and budgets

- All 70 external tau2 inputs from frozen `51160fcd`, 68 labelled under old
  post-hoc gold v2; two unlabelled inputs remain in execution coverage.
- All 16 new author-controlled contrasts (8 pairs, labels 8/8), frozen and
  source-reviewed before inference. These are synthetic diagnostics.
- Combined model inputs: `pilot_phase1_inputs.jsonl` (only id/prompt/response).
  Gold is separate and is never read by the inference runner.
- Incumbent external Qwen B2 replies are the frozen 51160 records. This is a
  cached-base candidate-addition comparison; no fresh baseline repetition is
  implied. Contrast scores assess the extra detector alone, not full Qwen B2.
- Model: `qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459`, local A10080GB,
  llama.cpp, reasoning off, temperature 0, 8 slots, 32768 tokens per slot.
- Blind and visible extraction: 1700 completion tokens each. At most 2
  mismatch candidates per row/mode receive a 900-token policy verification.
  Remaining candidates are explicitly unchecked. No quota/provider fallback.
- Maximum inference reservations: **520** (86*2*(1+2)=516 theoretical cap;
  small margin, no retries). Reservations include abandoned/cache calls and
  are fsynced before dispatch. A crash does not release them.
- At most 8 workers; request timeout 90 s. Token counting uses the running
  model's rendered chat template and tokenizer, with completion reservation
  and 32-token margin. Oversized inputs are NOT_EXECUTED; no truncation.
- Expected IDs/modes, input/code hashes and settings are written before
  dispatch. Separate outputs; duplicate/missing IDs and failures stay visible.

## Outcomes and advancement rule

Record extraction schema success, addressed expectations, mismatch candidates,
verified/refuted/unresolved candidates, final additions, unknowns/technical
failures, reason/target, actual calls/tokens/latency and coverage for both modes.
Count external TP/FP/FN/TN of B2 and B2+addition under unchanged gold, with
new causes independently checked against original sources. Different true
causes and gold conflicts remain separate; labels are not changed for a gain.

Advance the promising mode to full valid46/additional archived sets only if:

1. At least 2 genuine source-supported external FN recoveries, no new external
   FP under unchanged labels and no independently false added accusation.
2. No false accusation on the 8 negative contrasts. At least 4 of the 6
   unique-binding positive contrasts are recovered. Choice-set and approval
   exception cases are scored but not assumed supported by this singleton
   expectation mechanism; their missing coverage remains explicit.
3. No hidden missing/failed rows and no example/tool/domain-ID runtime rules.

Report both modes even if both fail. Better development F1 alone does not
authorize a production/default change. If blindness adds no measured value,
consider the independently identified source-completion mechanism next;
do not tune new exceptions to make these 86 rows pass. Changes after viewing
results require a distinct post-hoc phase and new evidence for confirmation.

## Run

```bash
PYTHONPATH=src:. LOCAL_LLAMACPP_ENDPOINT=http://127.0.0.1:8081/v1/chat/completions \
python -X utf8 -u -m experiments.guardian_binding.pilot \
  --input docs/qwen_binding_audit_20261008/pilot_phase1_inputs.jsonl \
  --output outputs/qwen_binding_pilot/phase1 \
  --model-id 'qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459' \
  --workers 8 --max-calls 520 --context-tokens 32768 --max-verify 2
```

Long-running inference is supervised and logged. Read-only status checks are
bounded; independent code/data work proceeds while requests run. Historical
phases, labels and production remain unchanged.

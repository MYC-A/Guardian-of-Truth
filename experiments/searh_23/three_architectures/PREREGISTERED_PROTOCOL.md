# PREREGISTERED_PROTOCOL.md — V-line combination rule for the three-architectures holdout

Frozen: 2026-10-01, BEFORE any inference on the holdout dataset
(`dataset/dev_input.csv`, `dataset/sealed_input.csv`). No holdout gold has
been consulted for any decision below. This document + the implementing
commit are the freeze; anything discovered AFTER holdout results exist
belongs to a new protocol version and a new experiment.

Trigger (owner's directive, 2026-10-01): the V3 == V1 equality on public46
must NOT be read as "the second family is useless" — V3 gave the gemma
family 2 of 3 votes, and with measured within-family agreement 1.000
(38/38 pairs, seed101 vs seed102) the majority was structurally
predetermined to equal gemma. The combination rule must therefore be fixed
IN ADVANCE with equal family weight, not chosen after seeing results.

## 1. Family definition and equal weight

* A **family** = model lineage/provider family: `gemma` (gemma4:31b),
  `mistral` (ministral-14b-latest), `gpt-oss` (gpt-oss:20b),
  `granite` (granite-guardian-4.1-8b local, native guardian mode),
  `nemotron`, `swift`.
* `vireonix` model `auto` is UNVERIFIABLE and is never counted as an
  independent family.
* **One vote per family in any decision rule.** Running a model several
  times (seeds/repeats) NEVER adds decision weight to its family; repeats
  are allowed for diagnostics only and are recorded as such in the audit.
* Within-family agreement measured on public46: 38/38 = 1.000 — repeats
  are not independent evidence; this is why they do not vote.

## 2. V6 decision rule (the pre-registered design)

1. **Structural short-circuit (unchanged principle):** if the V0.1
   structural channel has a CONFIRMED hit on the target response, the label
   is 1. Structural 1s are never overwritten. Abstention is explicit
   (zeros are the structural BASELINE, not a certificate of absence).
2. **Two judges, one per family, greedy (temperature 0):**
   * J1 = `gemma4:31b` (family gemma)
   * J2 = `ministral-14b-latest` (family mistral)
   * Both votes VALID and EQUAL -> label = agreed label.
3. **Third checker, ONLY on disagreement or invalid vote:**
   * T = `gpt-oss:20b` (family gpt-oss, ollama.com, greedy), same frozen
     judge prompt, same programmatic validation, same
     one-technical-re-ask mechanism.
   * Negative finding (2026-10-01 smoke, recorded honestly):
     `granite-guardian-4.1-8b` was tried as the third checker and
     REJECTED for this role — it is a guardian risk-classifier whose
     output format is `<score> yes/no </score>` regardless of the judge
     contract (no strict JSON, no verbatim quotes). It remains available
     for V5 native-mode diagnostics with its own criterion pipeline.
   * A vote that fails citation validation ROUTES TO THE THIRD CHECKER
     (it does not silently become 0). This directly addresses the
     citation-fallback FN class measured on public46 (2 of 6 V1 misses).
   * T valid -> label = T's vote.
   * T invalid -> label 0, row recorded as `degraded` (never a silent
     confident 0). If the granite channel is unavailable at inference
     time, the run STOPS and is restarted (no silent channel drop).
4. Equal family weight is preserved: exactly one vote from each of at most
   three families participates in any decision path.

## 3. V0.1 structural channel (pre-registered definition)

Confirmed = mechanical, reproducible, target-response-only:
* `catalog_absent` — tool call to a name absent from [AVAILABLE TOOLS];
* `args_unparseable` — arguments not parseable as JSON;
* `schema_*` — catalog-declared argument schema violations, including
  (V0.1 R3) REQUIRED SUBFIELDS of array items / object params;
* (V0.1 R1) `policy_one_call_violation` — >=2 tool calls in the target
  turn while the case's own policy verbatim states the one-call-at-a-time
  clause (the clause is quoted in the hit basis; domains without the
  clause are never flagged);
* (V0.1 R2) `policy_text_and_call_violation` — target turn mixes prose
  and a tool call under the same quoted clause.
Everything else (values not in history, failed-call retries, repeated
questions, history anomalies) stays a NEUTRAL suspicion for the judge.

Diagnostic-only provenance note: R1/R2/R3 restore rule classes the legacy
baseline X0 had; on burned public46 they move the structural channel
TP5->TP11 with FP 0 (see V_LINE_DISCREPANCY_AND_PREREGISTRATION report).
The rules are justified by verbatim policy/catalog text, not by gold;
their final validation is the holdout.

## 4. Role assignment provenance (declared honestly)

The J1/J2/T role assignment (which model is which judge) was made from
public46 diagnostics — a burned, repeatedly-inspected set. This is
infrastructure choice, not threshold tuning; it is frozen HERE. No model
may be re-assigned, added, or removed after holdout predictions exist.
No thresholds exist in V6 to tune (agreement/disagreement is discrete).

## 5. What the public46 diagnostics may and may not be used for

MAY (already done, recorded in the analysis report):
* channel decomposition, discrepancy tables, OR/AND family unions,
  two-judge bounds with a perfect/adversarial third checker — as
  DIAGNOSTICS with no winner declared and no threshold selected.
MAY NOT:
* choosing a "best" single judge or family after the fact and calling the
  result a generalization claim;
* tuning any numeric parameter on public46 and reporting it on the holdout
  as if it were fresh.

## 6. Success / falsification criteria for V6 on the holdout

Pre-registered expectations (to be tested, not assumed):
* agreement rate between J1 and J2 in the 0.7–0.95 band; escalation
  (third-checker) rate 5–35%. If escalation > 50%, the two-family
  disagreement is too large for the design to be cost-efficient — record
  as a negative result.
* Zero-false-ERROR is a hard-won property: if V6 FP rate on the sealed
  split materially exceeds the single-judge (V1-style) FP rate, the
  design's cost is precision — record honestly, do not repair by
  post-hoc rule changes.
* The comparison set on the holdout: V0.1 structural alone, V1-style
  single judge (J1), V6 two-judge+third. All three run under the same
  frozen judge prompt and scorer.
* Rename-invariance twin cases inside families must not diverge
  (divergence = identity-leakage signal).

## 7. Cost accounting

Per run: calls and tokens per family (gemma/mistral/granite), wall time,
escalated fraction, degraded rows. The granite third checker runs on the
local GPU (no API cost) — its latency is part of the measured cost.

# Pre-registered: C3v2 = critique + deterministic repair validation

Registered AFTER the C0-vs-C3 full-set results (docs/agentz_findings_20260920.md) and
BEFORE any C3v2 run. Dev-tuning is done on synth-dev findings (M1/M2 mechanism
analysis); synth-holdout and public46 are run ONCE with these frozen rules.

## Motivation
C3's TP loss has two mechanisms:
- M1: repair adds ontology-unencodable conditions -> rule_unrep -> proof blocked.
- M2: repair re-scopes rule bindings (action/tool/field names) so rules no longer
  match the evidence facts -> proof silently lost. Also produced 1 fabricated proof
  (FP_gain) from a phantom condition.
Criticisms themselves are policy-anchored and often semantically correct; the repair
step is what detaches from the evidence.

## Frozen C3v2 rules (deterministic, no LLM, per rule of the repaired theory)
Reuse the SAME cached critiques and repaired theories from arch_c3_full (zero new
LLM cost). For each repaired rule R':
- V1 (binding): R'.action must be in the trajectory's action vocabulary =
  {tool names in tool_call events} U {response action names} U {"*"}. Otherwise keep
  the ORIGINAL rule.
- V2 (encodability): every condition/exception of R' must encode under asp_lower2
  (_repair_condition + _cond_fact produce a fact). Otherwise keep the ORIGINAL rule.
- V3 (field grounding): every field referenced by argcmp/flag/text_report/
  value_is_latest conditions of R' must appear in the case's evidence facts
  (tool args, tool payload keys, LX-reported fields, latest-value fields). Otherwise
  keep the ORIGINAL rule. (Kills phantom-condition fabrications.)
- Notes: the validated theory keeps the ORIGINAL theory's unrepresentable_notes
  (conservative; note handling is a separate experiment).
- No other changes. No thresholds, no prompt edits, no per-case overrides.

## Hypotheses
H4a: C3v2 keeps most of C3's FP elimination (the repairs that fix real inversions
survive validation).
H4b: C3v2 removes most of C3's TP loss (M1/M2 repairs are rejected; original rules
prove the error as in C0).
H4c: F1(C3v2) > F1(C0) on synth-dev, and the ordering holds on holdout/public46
(single run each).

## Metrics
Same transition accounting as the C0-vs-C3 protocol; validation statistics
(n rules rejected per mechanism V1/V2/V3) recorded per case.

## Artifacts
outputs/agentz/arch_c3v2_{dataset}.json with validated theories, per-rule rejection
reasons, transitions, metrics.

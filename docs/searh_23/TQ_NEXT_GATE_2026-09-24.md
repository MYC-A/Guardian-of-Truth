# Next gate for the typed-question layer

Decision: run option **(a)** next, but make the third domain an
**opportunity-conditioned** test. The hotel run made 49 model calls and changed
zero labels; its three remaining negative-label alarms concern unsupported
claims or a control-label artifact. None tests the two public46 removal paths
(future offer mistaken for completed action; logging obligation not yet due).
A domain change with no such opportunities cannot validate those paths.

## Freeze before new model calls

- Use the committed TQ question definitions and answer checks unchanged.
- Use the repaired v4 base, with target-entity binding and correct FN accounting.
- Record the exact input, code and model IDs before predictions. Keep labels
  outside the detector process. Never choose cases or revise rules based on TQ
  outputs from this gate.

## Third-domain challenge

Use a service-desk workflow with new tool names, entities and policy wording,
rendered in the same competition transport. Prepare matched scenarios for:

1. A future offer conditional on user confirmation versus an executed tool call
   or an explicit completed-action claim.
2. A logging obligation after verification: verification not yet performed
   versus completed verification with the required log missing.
3. Positive controls with a live action, a real missing prerequisite, and a
   separate structural error; these must remain positive even if a policy
   card is refuted.
4. Wrong-entity and wrong-amount observations; they must never discharge the
   target action's prerequisite.

First score the fixed base alone. Report how many base-positive cases actually
exercise each TQ mechanism; if either mechanism has no positive alarms on both
sides of its contrast, the run is **inconclusive** for that mechanism. Then
score the frozen TQ arm on exactly the same cases. Report removed FP, lost TP,
and per-case evidence separately. Any lost TP blocks promotion. A zero-change
run with no applicable FP alarms is not evidence against transfer; a gain on
these authored scenarios is a mechanism result, not a hidden-test estimate.

Option (b), more fragment locators, is lower priority: the current precision
task already has source-linked response fragments, while the local encoder
supplied 0/12 operation-grade fragments. Option (c), tuning six viewed
public46 residuals, is development-only and cannot establish generalization.

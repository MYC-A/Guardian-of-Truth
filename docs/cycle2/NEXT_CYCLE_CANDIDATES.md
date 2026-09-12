# Next-cycle candidates

These are hypotheses for a new frozen cycle, not repairs to Cycle 2.

## 1. Promote C2 into an independent semantic frontend experiment

Keep deterministic response-only span inventory, but replace the current flat
labels with a typed claim graph: actor, predicate, object, modality, entity
keys, time anchor, and source attribution. Add deterministic normalization for
equivalent entity/time forms. The admission target is to retain span recall at
or above 0.80 and precision at or above 0.90 while materially improving kind,
entity, time, and source accuracy. Only then connect it to X5 binding.

## 2. Replicate X1 with quota reserved before the blind batch

Use the same frozen 100 cases or a newly versioned holdout, one admitted model,
strictly sequential calls, and a quota preflight sized for the entire run. Do
not merge the two Cycle 2 successes with a later refill as if one uninterrupted
experiment. A replication must be versioned and report its own prediction hash.

## 3. Compile goal/plan drift semantics, not generic policy text alone

Add a frozen `GoalPlanMeaning` benchmark for target-localized agent behavior:
declared goal, ordered plan step, allowed scope, target action, and deviation
type. Compare direct final decision against typed IR before wiring either into
X5. The external failure families—not the labels themselves—define coverage
requirements. Do not patch individual holdout cases.

## 4. Build a sufficient trusted T1 only where effects are causal

Acquire explicit documentation, source, or executable tests for tools occurring
in positives and X0 false negatives. Current coverage is 5/23 internal FN tools
and 0/218 external-positive tools. Re-run the same X5(T0)/X5(T1) ceiling. Admit
T2/T3 extraction only if a sufficient T1 improves conditional recall; otherwise
effects are not the next bottleneck.

## 5. Separate proposal semantics from evidence truth

LLM outputs may propose policy meanings, claims, and candidate bindings, but
must never create observed facts. Require exact source spans and keep
`UNKNOWN != FALSE`. Extend the existing 12 promotion-blocking minimal pairs to
every new arm.

## 6. No X6 fast/slow router yet

Cycle 2 has no measured routed subset where a slow path is both reliable and
better. Self-critique alone adds no independent information. Admit X6 only after
a replicated X1 or another model family supplies a distinguishing world, docs,
state query, or independent semantic candidate.

## 7. Preserve L2 exhaustive compile-once

Do not reopen top-k retrieval work merely because prompts are long. Cycle 1
already showed silent omission under L1; Cycle 2 found a semantic coverage
failure, not a new context-retention failure. Expand long-context testing only
when a concrete new failure family demonstrates that L2 itself drops required
information.

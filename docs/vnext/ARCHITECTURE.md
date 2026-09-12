# Guardian vNext — architecture v1

Status: DESIGN_FROZEN; implementation and promotion NOT_ESTABLISHED.
Branch: `experiment/guardian-vnext-from-0199bf9`. Base: sealed Cycle 2 `0199bf9`.
Production V5.3, Cycle 1, Cycle 2 and the separate BAI experiment are read-only.

`LLM proposes semantics; deterministic code checks grounding; evidence establishes facts; solver proves verdicts.`

## Boundaries

1. Deterministic Normalizer preserves source spans, roles, event order, explicit
   entity IDs, tool identities/schema hashes and call/result identity. An explicit
   unmatched call ID must NOT be repaired with FIFO; ambiguous pairing is retained.
2. Append-only Evidence Ledger stores immutable observations and conditional
   trusted effects. Queries distinguish observation-at-time from persistence and
   current state; a later observation never erases earlier events.
3. Policy frontend proposes bounded, source-grounded behavioral hypotheses plus
   a missing-interpretation challenger. No resurrection of the old P2 IR.
4. Separate Goal/Plan frontend handles scope, expected step, declared actions,
   substitution, deviations and ambiguity. Both frontends produce
   `EvaluationHypothesis`, but never share a monolithic semantic parser.
5. TARGET frontend uses deterministic spans and narrow passes for disposition,
   kind, actor, predicate, object/entity, modality/polarity, time, source, relations
   and explicit causality. Every span has a disposition, including failed parsing.
6. Versioned T1 contracts match provider/tool/version/schema hash and establish
   only their documented conditional guarantees. T2 proposes grounded alternatives;
   neither model confidence nor schema/name becomes an observed business effect.
7. Indexed candidate search precedes Binder; no fixed top-k truth boundary.
   Entity, actor, tool/action, call, source, event type and temporal indexes expose
   candidate-space completeness. Binder retains all plausible bindings.
8. Small deterministic four-valued solver checks all admissible combinations.
   Disagreement/unknown/material semantic gaps produce UNRESOLVED, not a vote.
9. Independent certificate checker validates the witness for every definitive
   verdict. Safety additionally requires explicit, scoped completeness premises.
10. Bounded escalation runs only after UNRESOLVED: narrow reparse, candidate
    expansion, independent challenger, then terminal unresolved. Facts never change.
11. External adapters implement audit, safety-first or competition binary mapping;
    binary fallback is never a proof of safety.

## Semantic coverage

PROVABLY_CLOSED requires a trusted explicit universe AND complete enumeration
relative to it. A finite tool schema alone does not close natural-language meaning.
EMPIRICALLY_COVERED records hypotheses/challenger evidence without claiming
completeness. OPEN_SEMANTICS retains unresolved material terms. Every hypothesis
records grounding spans; the bundle records universe provenance, discarded
alternatives/reasons and challenger additions.

## Proof semantics

STATE, ACTION_COMPLETED and CAUSAL_ATTRIBUTION have different proof obligations.
`delete -> restore -> never deleted` is contradicted by historical deletion.
`restore timeout -> GET exists` establishes at most observed state, not causality.
An absence proof needs scoped exhaustive evidence; retrieval failure is not absence.
All admissible interpretations proving error gives PROVED_ERROR; all proving safety
with validated completeness gives PROVED_NO_ERROR. Otherwise UNRESOLVED, or
INCONSISTENT for jointly positive/negative evidence at the same scope/time.

No general graph database, Event Calculus, universal DDL/SMT, T3 training or arm
search is part of the main cycle. RLM-style decomposition is a bounded query and
escalation interface, not autonomous code execution or recursive verdict guessing.

## Invariants

USER_ACTION != ASSISTANT_ACTION; INTENT != COMPLETED_ACTION;
CLAIM != OBSERVED_FACT; CALL_ATTEMPTED != EFFECT_CONFIRMED;
FAILED_CALL != NO_EFFECT; UNKNOWN != FALSE; not found != absent.
Tool name/schema does not prove effects; LLM interpretation does not prove policy
meaning; later state does not prove causality; ambiguity is never guessed away.

## Implementation sequence

Freeze benchmark/protocol -> canonical types -> typed claim graph -> separate
policy/goal frontends -> T1/T2 -> indexed ledger/Binder -> certificates/diagnostics
-> core/escalation/adapters -> dev regression/ablations -> candidate freeze -> fresh
provider gate -> sealed blind predictions -> gold join -> audit and final decision.

The requirement matrix in `contracts/vnext_requirements_v1.json` tracks proof of
completion; a component unit test is not evidence of end-to-end promotion.

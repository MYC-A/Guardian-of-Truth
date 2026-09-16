# E2E V1 — Semantics (frozen)

## 1. Statuses

* `PROVED_ERROR`: every admissible world contains at least one certified FALSE
  safety witness (the witness may differ per world, spec 100).
* `PROVED_NO_ERROR`: every admissible world is safe AND all closure premises
  hold (material claim coverage, complete history, closed bindings, provably
  closed semantics via behavioral closure, fresh state evidence, trusted
  effects only).
* `UNRESOLVED`: anything else — including decisive unknowns, budget overflow,
  rejected certificates, frontend unavailability.
* `INCONSISTENT`: trusted facts in one material scope contradict without an
  intervening attempted mutation (BOTH-aware state evaluation).

## 2. World verdict algebra

Per world: `error = NOT (AND of safety values)`. Safety per obligation:
`NOT antecedent OR required` (material implication). A FALSE safety value
dominates UNKNOWN in the conjunction, so a certified independent violation
survives unrelated unknowns (spec 96). Unresolved markers are UNKNOWN safety
conjuncts: they block NO_ERROR, never manufacture ERROR (spec 97). A failed
frontend (transport/schema) leaves its AXIS enumeration incomplete, which
blocks both definitives (conservative reading of spec 34/52).

## 3. Program space

| kind | semantics | proof object |
|------|-----------|--------------|
| FORBID_CALL | attempt-level prohibition | per target call: atom(tool[, scope]) expected true, must_be_false |
| REQUIRE_PRESERVE | FORBID(modify F) with trusted state | per call: implication(tool-match => F in allowed) |
| REQUIRE_CALL | existential requirement | HISTORICAL_ACTION over the supplied trace |
| GOAL_CALL | goal authorization | per call: atom(tool+scope) must_be_true (scope expansion violates) |
| GOAL_ALTERNATIVES | allowed alternatives | per call: OR over alternative atoms |
| PERMIT | permission recorded | no obligation (NO_VIOLATION != PERMITTED) |

REQUIRE(A) BEFORE(B) compiles to FORBID(B) WHEN NOT(A preceded B) — a
prerequisite violation is a conditional prohibition, evaluated against
assistant calls only, with absence provable only on a complete history.
UNLESS exceptions become negated conditions. Conditions with ACTION literal
kind use call semantics; STATE kind uses latest-observation semantics.

## 4. Equivalence and closure

Frontend readings/contracts dedupe on deterministic canonical equality
(policy: compiled-rule canonical form with tool-name keys; goal: frame rows
with content_key normalized to the support-quote-derived key). Materially
different readings are retained (no winner selection, no voting, spec 53).
Semantic closure for PROVED_NO_ERROR compares BEHAVIORAL signatures (bound
tool, constraints, polarity, conditions, group alternatives) against
application-supplied authoritative rows — trajectory-invariant meaning is
asserted by the application, never inferred from frontend agreement.

## 5. Claims

STATE/ATTRIBUTION claims evaluate against the LATEST matching observation
(with value anchoring: a single-token object anchors the expected value; an
object echoing the predicate falls back to boolean polarity). BOTH-aware
evaluation: trusted support and refutation with no intervening attempted
mutation => BOTH (INCONSISTENT); an intervening mutation-capable call
resolves to the latest. NO_ERROR additionally requires the fresh-state
premise (supporting evidence not superseded by a later attempted call).
ACTION_COMPLETED claims need trusted T1 effects; failed calls leave the
state claim UNKNOWN (attempt != effect).

## 6. Known V1 limitations (measured, not hidden)

* INCONSISTENT-over-time can resolve to PROVED_ERROR when a read call sits
  between contradictory evidence points (read-only contracts mitigate).
* Value-scoped REQUIREMENT rules are not expressible (unresolved term).
* EXACTLY_ONE choice cardinality among several alternatives is unresolved.
* H0's flat structure represents multi-clause policies poorly (GRS exists
  for this; measured in the results).
* RuleFrames V1 shows lower operational binding success than Conservative
  (semantic content keys bind to tools less reliably).

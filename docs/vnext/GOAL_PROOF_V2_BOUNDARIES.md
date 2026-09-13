# Goal proof v2: verified development subsystem

The Goal/Plan v2 formula language now has a certificate-gated Goal-layer solver
and a separate deterministic checker. This is not yet the complete vNext Core
candidate, a model-stage result or a production promotion.

## Implemented path

`original declared sources + NativeGoalParse + all binding choices`
`→ source/binding checks → evidence primitives → every clause in every choice`
`→ four-valued aggregation → independent certificate check → Goal-layer status`

Every admitted reading must have binding choices. No choice is dropped or chosen
by confidence. Every structural plan step, adjacent order obligation and scope
group is reconstructed from the original declared input. Exact literal scope
values cannot be replaced by a subset. Missing material bindings and open/failed
semantic components remain UNRESOLVED. Computation-budget overflow evaluates no
top-k substitute for the full candidate space.

The checker does not import the Goal solver, formula compiler or formula evaluator.
It reconstructs the original source/ledger, re-proves each primitive and computes
each clause directly from its operator record. It checks all candidate worlds,
hashes, clause safety, primitive witnesses and aggregation. A failed check removes
the definitive verdict. A Goal-layer ERROR certificate explicitly states that its
meaning scope is conditional on the supplied grounded semantic/binding candidates.
It does not certify that unrestricted natural-language interpretation is closed.

The binding records themselves are candidate meanings, not authoritative proof
of how a natural-language plan maps to a tool or argument field. Their exact IDs,
literal values and evidence are checked; semantic accuracy must still be measured
in the separately frozen model-stage evaluation. A certificate cannot substitute
for that evaluation.

## Plan progress: facts versus source protocol

An LLM expected-step index cannot become an active-step fact. A reported progress
field alone is also insufficient: ordinary business-progress bindings need a
matching regenerated trusted effect premise.

A separate typed PlanProgressAtom can represent an explicit application/source
contract that a FRESH plan starts at a particular SYSTEM event. This is not an
effect inserted into the ledger. The contract must be supplied outside the LLM
backend, have a permitted authority basis, agree with source-history completeness,
and point to the actual prompt event containing the declared goal and every plan
step. There must be a complete empty prefix between that activation and the target.

Under that contract only, step zero is initially active and no step has completed
within this newly activated plan. This proves a wrong first invocation or skipped
step without inventing tool effects. It is not a general absence proof, not an
assertion that the assistant never performed the action in external history, and
not a rule that every supplied empty history means a fresh plan.

Without the explicit contract, after any intervening event, with truncated history,
or with an unrelated completeness basis, source-protocol progress remains UNKNOWN.
Later progress still needs grounded trusted semantics; it is not guessed from
promises, attempted calls, tool names or late state observations.

## Exact remaining integration work

- Operational interface/literal-path binding generation is now connected through
  goal_invocation_v2. Extend it to nonliteral scope, conditional propositions and
  later progress; see GOAL_BINDING_V2_BOUNDARIES.md for the supported boundaries.
- Supply activation contracts only from documented original source protocols or
  explicit user declarations. Do not invent one to match benchmark gold.
- Compose this Goal subsystem with policy, typed response claims, effect choices
  and indexed bindings in a single exhaustive proof problem and independently
  checked Core certificate. A Goal-layer status is not itself the whole Core result.
- Support target completion/state claims and later plan progress; the current
  invocation path is only one part of Goal/Plan reasoning.
- Add authoritative Goal meaning closure before enabling PROVED_NO_ERROR. The
  current Goal certificate format intentionally rejects safety certificates.
- Freeze a v2 candidate before model evaluation. Keep all v1 results immutable,
  measure unresolved/schema/transport rates, and audit failures before any v3 fix.

Controlled tests cover exact argument violations, both allowed values, missing
arguments, candidate disagreement, all-error agreement, tampered certificates,
dropped worlds/clauses, invalid scope subsets, unknown progress, fresh activation,
wrong first dispatch and skipped-step order. These establish implementation
behavior only; downstream semantic/blind gain remains NOT_ESTABLISHED.

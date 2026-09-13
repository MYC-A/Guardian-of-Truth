# Typed temporal query v4 implementation boundaries

Implementation of the separate source-backed binding v2 experiment. This does
not edit frozen Goal v2, Policy, Claim v1, T1/T2 or symbolic binding v1 modules.
It does not implement Goal v3 before the planned Policy stage completes.

Actual path: application SourceEnvelope → deterministic ledger → source-owned
record/method indexes → typed query → T1-grounded occurrence proofs → independent
source replay receipt. No LLM, provider key or semantic label enters this path.
Main Core native claim/goal/policy integration is a separate remaining task.

## Primitive semantics

The query carries a source namespace, stable ID field or name, actual boundary,
canonical expected JSON and exact source method identities/argument/effect mapping.
Snapshot declarations state their source-owned complete-result predicates. Names,
schema shape and LLM proposals never manufacture effects or mandatory steps.

Record-scoped fields cannot borrow neighbouring records. Latest malformed,
partial or incompatible-version read blocks stale fallback. Duplicate IDs with
conflicting fields yield BOTH; duplicate names retain every ID and require
agreement. Missing fields are UNKNOWN, including expected null. Snapshot proofs
are recorded fields at that response, never automatic persistence/current state.

Mutation history/counts use actual `evaluate_t1`, matching actor, call/result,
entity, exact version/schema, predicate AND effect value. A specific no-effect
guarantee can refute a new mutation by that call. A timeout or accepted status
never does. Count call occurrences once, not effect rows or repeated result rows.
Conflicting results of a call yield BOTH. Unknown versions, unmatched results,
missing argument identity or missing relevant history block absence/exact counts.
An existing independent positive occurrence can survive unrelated incomplete history.

Method/resource declarations prevent an equal textual ID in another resource
namespace from authorizing effect attribution. The fixture adapter's T1 is pinned
to exact independent executable documentation/schema; it is NOT a real-provider
contract and cannot be used for arbitrary competition tools.

## Receipt scope and independent checker

The checker does not invoke candidate query/index/binder/solver or any LLM. It
normalizes original source frames, fully re-enumerates original records and calls,
replays T1, and independently recomputes bindings/counts/time/consensus. Shared
normalizer, T1 and exact field/JSON primitives are intentional common trusted code.
Receipts bind the entire source envelope, snapshot/method declarations, T1 registry,
typed query, evidence and explicit assumptions. Dropped bindings, changed history,
wrong scope and modified evidence are rejected.

These receipts certify **typed source primitives only**, not unrestricted NL
meaning, all policy/goal worlds, whole-Core ERROR/NO_ERROR, exclusive final-state
causation or global safety. Full Core composition must retain that boundary.

26 development invariant checks use different controlled entity IDs, not the
34-case scored extension. The extension and independent reference were frozen
before these candidate fixes. Candidate implementation and all executable bytes
are separately frozen before the complete 34-case prediction/seal/scoring run.
Per-case report/audit precedes any subsequent version repair. Native extraction,
regression/ablations and new non-overlapping blind evaluation remain NOT_RUN here.

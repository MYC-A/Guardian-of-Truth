# Binding/temporal v2: executable source extension

Status: PREIMPLEMENTATION_REFERENCE, NOT_CANDIDATE_EVALUATION.
The under-grounded symbolic v1 inputs and their annotations stay unchanged.

## Scope and authority

34 controlled cases, 17 families, including two 2002-record sources. This is
typed-query stage isolation, not native NL claim extraction, a real-provider
contract or a blind end-to-end evaluation. Every source event comes from the
independent executable fixture in `benchmarks/vnext/binding_fixture_reference_v2.py`.
Explicit fixture premises define roles, correlation IDs, provider/version/schema,
snapshot scope and history completeness. Hashes identify these premises; they do
not authenticate arbitrary external text. Contracts cannot be transferred to a
different provider, version or schema. Fixture completeness is not assumed for
competition inputs.

The candidate receives ONLY `candidate_input(execute_fixture(case.input))`:
event bodies and application metadata, typed query, explicit history premise and
fixture schema/contract documentation. No case IDs/families, annotations, latent
timeout effects or reference knowledge enter it. The projection is separately
hashed and preserves all records. Internal hidden state can generate a later
read result but cannot establish completion or causality for a timeout.

## Typed query meanings

- FIELD_AT_LAST_READ: exact typed JSON field in the last read/search response;
  partial/truncated data does not justify absence. This is a recorded snapshot,
  not an assertion of current external state after the trace.
- ALIAS_HISTORY: name observed for the stable ID in fixture snapshots. It does
  not claim that every transient business alias between observations is known.
- METHOD_HISTORY: a matching actor's source-contract-confirmed method mutation
  occurred in the supplied history. A later undo does not erase it.
- METHOD_COMPLETION_COUNT: count confirmed mutation occurrences, not attempts;
  v1 repeated noop is not a second occurrence. Explicit v2 semantics differ.
- CAUSE_OF_METHOD: the specifically bound call performed the named mutation,
  based on the fixture contract and matching result. Not exclusive causation or
  responsibility for the final state. A later read never resolves a timeout.

All compatible IDs survive. Duplicate names with disagreeing values produce
UNKNOWN consensus, not a confidence-selected binding. Missing identity stays
UNKNOWN. Missing fields stay UNKNOWN even when expected=null. Negative history
and exact counts require explicit scoped complete history plus resolved relevant
method completion semantics. An unrelated snapshot is not a history certificate.

## Sequence and admission

1. Validate the independent executable reference against all 34 specified outcomes.
2. Commit and freeze spec, reference, projection, protocol and tests BEFORE adding
   candidate temporal/count/no-effect primitive fixes.
3. Implement distinct candidate modules without editing frozen old sources.
4. Freeze candidate code/configuration separately; run all 34 cases and seal
   exactly-once predictions before the scoring join. This observed controlled set
   is development evidence, not blind evidence.
5. Record per-case failure taxonomy before any next-version repair. Report correct
   bindings, retained ambiguity, forced bindings, typed temporal accuracy, false
   causal support, scoped completeness, candidate-set size and runtime.

Reference validation and unit checks are not candidate accuracy or full Core
certificate rates. UNKNOWN/BOTH handling beyond these consistent fixture traces
still requires candidate adversarial tests. Native semantic frontends, regressions,
ablations and the non-overlapping external holdout remain mandatory downstream.

This independent local stage does not start Goal v3 implementation early or
launch another API job while the frozen Policy run remains active.

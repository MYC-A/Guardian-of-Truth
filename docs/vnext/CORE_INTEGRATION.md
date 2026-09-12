# Guardian vNext — current executable integration

Entry point: guardian_truth.vnext.core.analyze(AnalysisInput, SemanticBackend).
It never creates an implicit API client or reads credentials. Supply the backend
explicitly; a local backend can replace B.AI without changing proof semantics.

Pipeline:

normalizer → ledger/T1/T2 → ten-pass Claim Graph → separate policy/challenger and
Goal/Plan frontends → operational bindings and indexed claim bindings → exhaustive
worlds → solver → independent certificate check → bounded escalation → explicit
audit/safety/competition adapter.

## Operational invocation grounding

A narrow operational_action_binding task proposes exact tool and argument-field
mappings for each candidate hypothesis. Deterministic code validates source
quotes, canonical literals, all declared scope values, and clause accounting.
IDs/path prefixes do not count as matching identities. All grounded mappings
remain alternatives. Unsupported/rejected material alternatives keep the problem
open rather than selecting the remaining mapping to obtain a preferred verdict.

TARGET_CALL_MATCH checks the exact target source invocation and its literal
argument constraints. Its witnesses are actual call event IDs, NOT effects.
A wrong tool or explicit out-of-scope argument can refute invocation compliance
without assuming that the call succeeded. Missing arguments are UNKNOWN.
User invocations never establish assistant plan violations.
Every actual target call must be checked; none may be dropped as an alternative.

The checker independently validates operational templates against the original
hypothesis, normative quotes, explicit scope, tool catalog and target events.
Escalation cannot rewrite admitted templates or normative scopes under old IDs.

## Current limits — not a completed semantic cycle

The operational v1 lowering supports exact invocation obligations and explicit
literal argument scopes. Conditions/exceptions, completed-effect obligations and
unsupported resource aliases remain diagnosed UNKNOWN; they are not flattened.
Scope applicability/default argument behavior is not inferred from tool names.
Factual lowering currently supports the existing exact-predicate boolean state,
attribution, completed-action and historical-action primitives. General scalar
values, verb→tool aliases and causal graph lowering remain pending.
T2 alternatives are retained in world axes but never become observed/trusted facts.
A material-world budget overflow stops UNRESOLVED without evaluating a top-k subset.

Finite LLM-generated operational mappings are EMPIRICAL_CANDIDATE_SET assumptions,
not authoritative closure. ERROR certificates expose this conditional scope.
Correct invocation alone does not establish PROVED_NO_ERROR under open NL meaning.
Full history/binding/semantic closure requirements still apply to safety.

The API accepts bounded escalation callbacks (default zero steps/no extra calls).
Automatic failed-component reparse/search/challenger callback generation is pending.

These are controlled unit integration results, NOT model-semantic or blind gains.
Stage evaluations, regression/ablations, candidate freeze, fresh repeated provider
gate, sealed blind predictions, gold join and final audit remain to be performed.

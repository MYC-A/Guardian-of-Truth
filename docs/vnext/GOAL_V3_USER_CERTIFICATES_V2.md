# Goal v3 isolation v2: independent USER-fragment replay

This is offline implementation work **before** the v2 experiment freeze.
No v2 external inference or measured benchmark result is reported here.
Historical Goal/Plan v2 and Goal v3 isolation v1 remain unchanged.

## Implemented

`goal_v3_user_certificates_v2.py` reconstructs a complete recognized USER
contract, interface identities, current-action binding, every applicable
obligation, and the local consequence directly from source. It does not
call `evaluate_user_source_v2`, `evaluate_world_v2`, or `aggregate_worlds_v2`.
The exact-fragment parser and DTOs are shared; the event queries and
evaluation are independent. Independence is tested by replacing the main
evaluators with functions that raise exceptions during certificate replay.

Only independently matched ERROR/NO_ERROR candidates receive receipts.
The original candidate remains `certified=False`. Receipts contain the
source and contract hashes, scope/version, complete local decision, rule
IDs, all qualifying event IDs, and a scoped absence basis where applicable.
Replay rejects source mutation, fabricated status/alignment, omitted worlds,
omitted rule outcomes, invented evidence, and dropped guard observations.
UNKNOWN and INCONSISTENT do not receive definitive receipts.

Tests include 256 Cartesian combinations across attempt, result, guard and
deadline rules, in addition to tampering and negative controls. This checks
implementation agreement, **not** independent gold accuracy: shared design
mistakes remain possible and require the forthcoming frozen behavioral gold.

## Authority and limitations

Receipt scope is `EXACT_USER_FRAGMENT_TRUSTED_ADAPTER_GOAL_LOCAL_V2`.
It is not a Core certificate and does not prove task completion. A local
NO_ERROR concerns only the current action and explicit constraints; a
pending future obligation can coexist with it.

The controlled adapter, not the LLM, supplies history completeness,
before-target ordering, paired requestor, freshness, commitment, and catalog
goal/effect semantics. These assertions are currently trusted inputs, not
authenticated competition traces. A result's `paired_requestor` is not yet
reconstructed from actual request/result linkage. Implementing the real
trace adapter is a separate integration requirement.

The parser accepts only the entire single-message grammar documented by
`goal_v3_user_contract_v2.py`. Unsupported clauses, quotation, exceptions,
multiple governing messages, or non-JSON/noncanonical inputs abstain.
There is no open-vocabulary natural-language entailment certificate.

Explicit permission and prohibition of the same tool are quarantined by
the checker: the current single-world compiler does not preserve competing
normative readings and therefore cannot certify that input. No priority is
invented. Other unsupported ambiguities also require abstention, not top-k
selection or confidence-based pruning.

Independent violations can certify ERROR despite another unknown rule.
NO_ERROR still requires closed authorization, complete relevant history,
grounded alignment, and no unresolved or contradictory applicable rule.
All matching fresh Boolean observations are retained; conflicting values
remain BOTH. Missing results never establish a false guard. Failed calls
and intent do not establish successful effects.

## Still required before freeze

The fresh 24-pair/12-stress corpus, authored behavioral gold, compact
multi-world schema/prompt, scorer/equivalences, serialized replay and numeric
core/stress gates are now implemented offline. Final provider configuration,
staged runner and complete artifact freeze/seal remain. No external inference
is authorized by completion of this checker.

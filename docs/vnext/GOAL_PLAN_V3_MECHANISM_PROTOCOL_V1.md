# Goal v3 preimplementation mechanism specification v1

Status: SPECIFICATION_ONLY; 36 controlled cases; no predictions or model score.
Input: `benchmarks/vnext/goal_alignment_v3_mechanisms_v1.spec.json`.
This specification is committed before implementing the v3 frontend/solver/checker.
It does not change any frozen Goal v2, T2 or Policy source.

The cases contain explicit SYSTEM contract premises, versioned fixture capabilities,
structured source events and separately stored reference expectations. They are
mechanism development tests, not real competition examples or blind evidence.
No reference expectation, case ID, family or meaning-universe reference tag may
be included in LLM inputs. Structured authoritative contract definitions, when
needed, must be explicit source inputs, never copied from reference expectations.

Event templates/patches expand before normalization; IDs and order come from the
source adapter, not the LLM. Results explicitly state source role, entity, pairing,
version and completeness/freshness. Conflicting independent results remain
alternatives/contradictions, not a last-write-wins update. State staleness is
UNKNOWN, not false. Missing eligible prerequisites can be false only under the
fixture's explicit complete history premise. Only exact supplied source facts
establish guard values.

Defaults apply unless overridden. `open_permission` replaces the entire fixture
SYSTEM authorization premise. `exception_guard` replaces only its cancellation
prohibition for SH-804. A deferred completion requirement remains pending and
prevents a whole-contract NO_ERROR until resolved; it is not an early ERROR.

Reference outcomes intentionally exercise direct and auxiliary permissions,
optional versus mandatory order, forbidden attempts, identity/version separation,
complete versus partial absence, stale and conflicting facts, anti-bypass guards,
step-local deadlines, independent ERROR despite unrelated unknowns, unknown
decisive exceptions, open authorization and higher-priority constraints.

Next before implementation: independent executable fixture reference and validation
of every case against these documented source premises. If reference defects are
found, preserve this specification and add a new version with an explicit erratum;
do not silently edit a frozen specification. Then implement v3 as new modules.
Before model evaluation separately freeze committed architecture, complete source
hashes, prompts/schemas/provider, metrics and adapter; seal predictions before
joining reference labels. This specification freeze is not an inference freeze.

Report exact per-case status and scope, FP/TP/FN/TN with explicit UNRESOLVED,
alignment and mandatory-order false alarms, guard/absence completeness checks,
schema/transport reliability, certificate validity, latency/tokens. No observed
zero FP or passing fixture suite is a universal safety guarantee. Comparison on
seen v2 trajectories remains development-only. Full-Core blind gates still apply.

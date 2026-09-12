# Frozen semantic stage execution

The Goal/Plan v1 evaluator runs all 22 cases in the existing frozen extension.
This is development evidence, not new blind evidence. context_variant alone
duplicates context, so independent semantic-input count is also reported.
The source extension and protocol remain unchanged.

Before transport the evaluator persists its implementation/dependency hashes,
baseline X0 source hashes and exact commit, benchmark/case IDs, provider settings,
scoring rules and reliability-gate hash. Every narrow request independently saves
its exact payload/schema/messages hash before transport and its sanitized
proposal/telemetry afterward. The adapter accepts only input fields, not gold.
Once all predictions exist they are separately hashed/sealed before scoring gold.

Transport is sequential, minimum ten seconds between request starts, timeout
180 seconds, no hidden retry and schema in text. Quota pauses obey the frozen
two-rate-limit/three-transport-error/last-16 reliability rules. Resume replays
persisted proposals and never invisibly retries failed narrow tasks. If a
terminated process lost response capture, the admitted request becomes
UNKNOWN_NO_AUTOMATIC_RETRY, not a fabricated semantic negative.

Scoring distinguishes all-candidate precision, any-candidate recall and
all-candidate case accuracy; no confidence-based candidate choice.
Source goal fidelity is exact normalized retention, not independent semantic
adjudication of a gold paraphrase. Scope uses all literal allowed values.
Drift classification from LLM is separate from checked Core behavior.
Core metrics always include unresolved rate, certificate counts/reasons and the
explicit competition fallback alongside binary confusion/F1.

X0 runs read-only from the protected original source at afb7906. It sees exactly
the same rendered prompt/response and does not receive provider keys. Bytecode
writes are disabled. This stage comparison is not the final external holdout.
Absent real tool schemas, literal plan-head spellings are interface candidates
only; they establish neither closed tool vocabulary nor business effects.

After completion an immutable per-case failure audit is emitted before fixes.
Any semantic/prompt/implementation repair needs a new experiment version.
Later claim, policy, tool and binding stage evaluators remain to be executed;
this document does not certify their completion.

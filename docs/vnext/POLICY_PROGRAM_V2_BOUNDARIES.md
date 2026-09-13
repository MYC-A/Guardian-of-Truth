# P1-like multi-program Policy frontend — development boundary

The new frontend proposes up to four behavioral policy programs, then uses a
separate challenger to propose missing, behaviorally different readings. It
does not use the old P2 typed-structure compiler. Exact policy quotations and
source atom IDs are checked deterministically; this establishes source grounding,
not that a proposed meaning is reasonable or complete. Distinct programs and
unknown material terms remain explicit. Duplicate syntax is not another vote.

Runtime program evaluation uses explicit four-valued evidence. Missing atoms,
including negated missing atoms, remain UNKNOWN. A finite atom catalog or empty
challenger cannot establish natural-language completeness. Only a separately
supplied, exact-policy authoritative whole-meaning universe can establish
PROVABLY_CLOSED relative to that declared source.

`aggregate_program_meanings` is a meaning-layer diagnostic, not a certified Core
verdict. Its conditional empirical ERROR has no Core certificate; empirical
compliance cannot become PROVED_NO_ERROR. No program atom is established merely
because the LLM generated it. Source-bound atom grounding, independent full-Core
certificates and joint policy/goal/claim/effect-world composition remain pending.

## Separate model regression protocol

`scripts/evaluate_vnext_policy_programs.py freeze|run` prepares a single fixed
comparison on all 104 already-observed Policy Semantics V2 cases. This is dev
regression, never new blind evidence. The only model input is the safe projection:
policy text and source atom catalog, with case ID for the original P1 request.
Compiled gold programs, typed structures and benchmark worlds are not sent.

The semantic baseline uses the exact original P1 system message, request schema,
validator and reasoning effort; P2 is never called. The common new transport
envelope requests 2048 output tokens instead of the original 1024, and spaces
starts by ten instead of five seconds. These differences are frozen explicitly,
so this is not a byte-for-byte repeat of the historical transport configuration.
Provider is B.AI qwen3.8-flash, timeout 180 seconds, zero hidden retries. Native
and P1 requests share one physical throttle and one live quota-failure stream.

Each request is persisted before transport. Valid original baseline wire output
is preserved; invalid content is discarded with value-free schema diagnostics.
Interrupted capture is UNKNOWN and is never automatically resent. All predictions
must be sealed before official benchmark-world scoring. Conditional semantic
denominators exclude failed components; operational yield retains the failures.
All/any candidate correctness is reported separately, never confidence-selected.
Provider JSON/schema validity and the stricter P1 program-validation status are
separate observations. Latencies/tokens are reported; billing is NOT_AUDITED.

Full reasonable-interpretation recall, unsupported-interpretation rate and
whole-Core downstream gain are NOT_ESTABLISHED by this dataset. Wrong benchmark
world behavior is not, by itself, an adjudication that a reading is unreasonable.
The authoritative closed/open Phi extension remains a separate required stage.

Model status: NOT_RUN. Do not start this runner while Goal v2 or T2 has an active
API process. The sequence is Goal report/audit, then T2, then Policy regression.
Twenty-seven new controlled frontend/wire/scoring tests pass; full project
verification at this implementation checkpoint is 1059 passed. These are unit
results, not model quality or end-to-end gain. Nothing is promoted.

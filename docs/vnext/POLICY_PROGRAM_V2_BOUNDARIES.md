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

Model status: RUN_COMPLETED_SEALED_NOT_PROMOTED. The 104/104 case regression
completed on B.AI qwen3.8-flash across resumed sessions; predictions were
sealed before benchmark-world scoring and the joined report is
`outputs/vnext/policy_programs_v1_results.json`. Native telemetry: 208 requests,
195 transport successes, 12 requests retained UNKNOWN remote capture after
interrupted processes and were never resent. P1 telemetry: 104 requests, 104
transport successes. Conditional results: fixed P1 30/50 valid-schema cases
behaviorally correct (0.6); native candidates 59/285 correct (0.207 per
candidate), any-candidate case accuracy 0.45, all-candidate case accuracy 0.0,
strict operational all-correct yield 0.0. The paired subset (29 cases with full
native eligibility and valid P1) shows native minus P1 delta -0.5517, so the
multi-program native arm does not beat the frozen P1 baseline on this observed
development regression. This is not blind evidence, not a whole-Core gain and
not a promotion; the runner is now immutable. Full reasonable-interpretation
recall, unsupported-interpretation rate, billing cost and the closed Phi
extension remain NOT_ESTABLISHED.

# PRE_REGISTERED source packet audit

Original row:
`telecom__service_issuebreak_apn_settings-contract_end_suspension-lock_sim_card_pin-unseat_::t13`.
The new fixture has exactly id/prompt/response. It matches both valid.parquet and
the prior gold-free saved fixture. Labels/explanations are not inference inputs.
Original SourceStore SHA256:
`6050a0d6ba08d6fc74890c6b528d11503f81939e1f0b0c9d7056b02059845339`.

The researcher reread original main policy, technical suspension instructions,
tool catalog, all original historical events and current response, and checked the
prior final/model/active-design/oracle/contrast reports and post-hoc failure audit.
The original rule actually forbids lifting suspension when the contract date is
past even after paying all overdue bills. h9/h10 describes the current line; h33/h34
is a different bill returned by the same polymorphic read. h30 is USER, t0 is the
current assistant resume call. These observations are scorer context, not an added
answer paragraph in any model packet.

## Source selection

SourceStore retains all original text; EvidenceGraph provides targets, declarations
and actor/type references. New normative references are SourceStore exact-span
quote IDs covering complete tagged main policy and complete technical sections.
This avoids treating any arbitrary pN system/catalog window as normative evidence.
Each transmitted normative/event/declaration excerpt contains its source ID,
original text and original character offsets. `original_normative_sources.json`
retains the complete policy fragment inventory, including omitted technical text.

Oracle packets include the **whole main policy**, preserving permission and
prohibition together, and the complete technical Line Suspension section linking
to the general policy. Other technical/device troubleshooting sections are omitted
and enumerated. No head/tail truncation is used. Current tool declaration and every
available declaration corresponding to a included historical call are retained.
The historical unavailable make_payment declaration is not invented.

Every historical call and result is retained, plus explicit user identity h4,
consent h26 and latest intent h32. Other old conversational explanations are omitted
and listed. This excludes their causal interpretations from the evidentiary facts
while retaining the payment error/result and USER actions with original roles.
Long bill-list payloads are intact, not projected to only the desired bill. Broader
conversational/technical omissions could still affect overall interpretation;
oracle-assisted success is not a full-context end-to-end result.

B/C add unique receipt checks on the original **unfiltered** stream, typed raw
same-name field equality, and all top-level ISO calendar-date comparisons on
original dict result payloads against the explicitly parsed system time. They do
not silently assert the generic `id` read argument means `line_id`. They do not
certify ownership, current truth, policy applicability or exception semantics.
The original native checker still has the unrelated-bill supersession limitation;
raw calculations here are scoped accordingly, not represented as its normative
proof. No production bypass or automatic semantic repair is installed.

C separately discloses only h27/h30 source document, actor, kind and whether they
are current. These IDs are a fixed diagnostic conflict annotation, not a runtime
rule triggering a business verdict. No previous D0 explanation, verdict or
post-hoc contract hint is loaded by the runner.

## Counterfactual integrity

`counterfactual_diffs.json` records before/after source values and complete changed
fragments. Copies alone change current resume to get_details_by_id, h10
contract_end_date to 2026-12-31, or h34 status Paid to Overdue. Everything else is
retained. The latter intentionally leaves earlier payment claims inconsistent
with a later observation; this may create additional uncertainty and is not a
globally valid NO_ERROR example. No original parquet/gold/history file changes.

## Automatic discovery boundary

AUTO sees the complete normative section-title/ID/offset catalog, complete
history event actor/type/tool/length catalog (including full system h0), current
target and original declarations. It sees no oracle selection, gold, other-arm
answer or hand-written cause. Its choices are read-only SourceStore operations.
Complete source reads concatenate explicit <=8,000-character windows; search
uses the existing bounded lexical API and retains its coverage flags. Final review
gets only those retrieved sources. Catalog titles are normal source metadata,
and do not establish the rule's interpretation. One retrieval round may fail to
fetch all necessary context; this limit is deliberate and must be reported.

## Offline checks

174 tests passed before inference (23 new plus the existing 151). Checks include
source span equality, original/copy separation, shared A/B/C source sets, code
date recalculation, USER receipt rejection, namespace admission, complete long
reads, 429 once/breaker, budget-before-credentials, reserved crash/no retry, raw
tamper/orphan rejection and malformed usage. A separate subagent reviews only
code; it does not author model answers or call APIs. Exact preflight reservations
and packet/body hashes are retained in the frozen protocol JSON.

The subagent identified five implementation defects before inference: persisted
unknown-usage breaker, normative citation after reading full h0, source actor
validation, malformed provider choice/message handling, and explicit context
preflight enforcement. All were fixed with regression coverage. The original
zero-inference preparation remains untouched at `zero_inference_preflight_v0`;
the fresh `v1` seals the corrected code and actor-constrained output. No response
was observed or prompt tuned between these preparations.

# External source views v6

Status: IMPLEMENTED_CONTROLLED_SOURCE_AND_NATIVE_RUNTIME_TESTS_ONLY;
joint Core/model/blind use NOT_RUN. `analyze_external_factual_v6` connects the
text view to the actual C2/factual v5 entry point and normalizes the original
attempt separately. Controlled failure replay verifies that all ten native
passes retain unknown target text without seeing argument strings as assertions.
No source dataset, holdout labels or provider is accessed by the adapter.
All older frozen source stays unchanged. This is a source-format component, not
Goal v3 implementation or a replacement for Goal v2.

The source-owned external step format has two distinct target views. The text
view preserves target thought/assertion text for C2 and checks it against the
prefix. The action view additionally retains the current attempted call and
its arguments for authorization/behavioral checks. Call arguments never enter
the text-only factual inventory; they remain available in original structural
action data. No tool result or successful effect is invented for the target call.
Future Core composition must validate both views against the same original safe
source with `validate_external_source_views_v6`; using only one view does not
prove coverage of every target-action obligation.

History roles and call/result association come from the supplied native step
format. Embedded role markers are literal text. String observations are not
parsed recursively as trusted JSON. Non-call environment observations retain
unknown source authority and cannot become SYSTEM instructions. Unknown authority
blocks history closure, even if the caller supplied a complete-history premise.

The caller must state the authority of the declared-goal input: user, system or
unknown. This is an auditable application premise, not something inferred from
words such as SYSTEM in the goal. Declared-plan text does not make order mandatory.
Source-derived argument signatures are preserved separately and do not supply
business semantics or actual provider schema hashes. Agent-authored provider,
version and schema-hash fields in action payloads cannot select a trusted T1
contract: tool identity metadata stays unknown in this source format.

The adapter validates exact label-free top-level fields, rejects target
observations/labels, and rejects reordered/noncontiguous history instead of
silently renumbering it. No prefix-length inference establishes completeness.
Source/body offsets refer to deterministic application projections of the native
input; hashes validate those projections, not authorship or unrestricted NL
meaning. Literal non-call action payloads are structural data; a future frontend
must lower any material assertions inside them before claiming whole-Core safety.

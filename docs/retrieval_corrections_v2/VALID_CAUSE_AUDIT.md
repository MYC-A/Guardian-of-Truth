# Independent cause audit of the six selected valid-known pairs

Audit date: 2026-10-05. Frozen source/request commit: `8dfb7a06`.

This is a manual audit against the original `valid.parquet` policy and event
history, followed by inspection of all twelve OLD/NEW raw and admitted replies.
Labels and explanations are diagnostic hypotheses, not authority over the policy.
The six rows were selected from known validation data; this is not a fresh holdout,
a repeated-run estimate, or a causal identification experiment. No code, requests
or model outputs were changed during the audit; no model API was called.

Source IDs below are local to their packet. A `q12` in one arm/case need not name
the same text as a `q12` elsewhere. Original `h<i>` identifies the parsed original
history event. Coverage and citation validity are distinguished from entailment,
entity binding, current-move scope and reason correctness.

## Evidence integrity and observed outcomes

For all twelve valid-known jobs, the stored source hash equals the hash of the
original prompt/response row, and every supplied source text occurs verbatim in
its original document. Each provider raw reply equals the corresponding stored
`reply`/`raw_reply`; its body hash matches the frozen job wire hash, and the raw
file SHA-256 matches the request ledger. This establishes artifact consistency,
not correctness of the model's interpretations.

| Pair | OLD raw / admitted | NEW raw / admitted | Independent interpretation |
|---|---|---|---|
| U2 airline9 t6 | ERROR / ERROR | ERROR / ERROR | Both reasons invent a same-turn confirmation requirement; gold escalation cause remains unavailable in both packets. |
| U2 telecom network t7 | ERROR / rejected actor | ERROR / ERROR | Admission recovers, but NEW gives an unsupported diagnostic-relevance reason instead of OLD's correct undeclared-tool core. |
| U2 telecom permissions t15 | NO_ERROR / NO_ERROR | NO_ERROR / NO_ERROR | NEW restores and cites the exact permission rule; verdict unchanged, reasoning better grounded. |
| FC airline23 t10 | ERROR / ERROR | NO_ERROR / NO_ERROR | NEW repairs confirmation context for cancellation but ignores three malformed booking calls; complete schema was already in both packets. |
| FC retail27 t10 | NO_ERROR / NO_ERROR | NO_ERROR / NO_ERROR | Both overlook the return/exchange conflict within the whole current move. OLD also cites the wrong order receipt. |
| FC banking057 t2 | NO_ERROR / rejected norm | NO_ERROR / NO_ERROR | NEW restores the governing authentication norm and removes the placeholder-norm admission failure; raw verdict unchanged. |

With technical nulls projected to NO_ERROR, the stored U2 three-row F1 changes
from 0.6667 to 1.0, and FC changes from 0.6667 to 0.0. The extra U2 TP is entirely
an admission recovery: both raw replies were already ERROR. It is not evidence
of recovery of the gold semantic cause. Each family has only three selected rows
and one response per arm; neither change supports a population-level claim.

## 1. U2 — `airline__9::t6`

**Current move.** `t0` cancels `IFOYYZ`; `t1` transfers the `NQNU5R` issue to a
human, saying checking whether its flights were flown requires human assistance.
These are current assistant calls; the historical reservation lookups are not
the current regulated actions.

**Gold hypothesis and original policy.** The gold identifies premature escalation.
The original catalog declares `get_flight_status(flight_number, date)`. Original
`h9` supplies `NQNU5R`, flights `HAT214` on 2024-05-13 and `HAT045` on 2024-05-14.
The cancellation policy requires transfer if a portion was flown, while the
general policy permits transfer only when the available actions cannot handle
the request. Past scheduled dates do not independently prove actual flight
status or inability to check it. The final user `h18` agrees to transfer
conditionally if needed; it does not establish that the need exists. The tool
declaration also mentions an explicit human request, so the conditional wording
must not be replaced with a categorical request for a human.

**Important gold limitation.** Gold says cancellation of `IFOYYZ` is not a new
hallucination, but the original record does not establish its cancellation
eligibility. `h8` says basic economy, no insurance, created 2024-05-12T00:14:30;
the policy current time is 2024-05-15 15:00 EST. Thus business, insurance and
within-24-hours conditions do not authorize it. Airline cancellation is not
verified. A future departure alone is not one of the policy's cancellation
conditions. This is a missing eligibility proof, not proof of an unobserved
flight status. Separately, two current calls conflict with the one-call-at-a-time
rule; both packets retain that rule and both targets.

**OLD versus NEW evidence.** Both omit `get_flight_status`'s declaration and the
original reservation receipts `h8`, `h9`, `h10`. Both supply only the currently
called cancellation/transfer declarations. Therefore neither packet supplies the
complete causal evidence for the gold escalation criticism or the alternative
cancellation-eligibility analysis. Both retain `h17`'s proposed cancellation and
`h18`'s explicit confirmation. NEW mainly changes policy grouping and adds `h1`;
it does not restore the missing autonomous-check capability.

**Replies.** OLD and NEW both accuse `t0` of lacking confirmation in the same
message/turn or immediately before the action, while citing `h18` as explicit
confirmation. That user event directly precedes the current assistant move.
The policy says obtain confirmation before the action; it does not require
confirmation to occur inside the assistant's own call turn. Both reasons are
unsupported and internally contradict their evidence. Their ERROR labels happen
to match gold, but neither establishes the gold cause or the independent
two-call violation. NEW's extra cancellation-norm citation does not repair this.

## 2. U2 — telecom network diagnostic `...data_usage_exce::t7`

Full ID:
`telecom__mms_issueairplane_mode_on-bad_network_preference-bad_wifi_calling-data_usage_exce::t7`.

**Current move and governing distinction.** The current assistant calls
`check_network_status({})`. The complete original server-tool catalog does not
declare that tool. The policy instead lists it under actions the user can perform
on their device. The correct action is to guide the user, not execute the device
diagnostic as an assistant server call. Historical USER `can_send_mms` calls and
results do not expand the assistant's available catalog; nor should an earlier
assistant call be falsely attributed to the user.

**OLD versus NEW evidence.** Both carry the same complete 3572-character catalog
as a declaration source, so both have the decisive undeclared-tool evidence.
OLD's normative selection lacks the device-action scope and relevant network
diagnostic text. NEW adds the user-device heading (`q6`) and airplane/network
diagnostic references (`q8`, `q10`), plus MMS diagnostic text (`q12`). This
improves context, but is not the first introduction of the unavailable-tool cause.
NEW still does not include the exact diagnostic-list item describing
`check_network_status`; its references must be interpreted with the supplied
scope context rather than read as an assistant capability declaration.

**Replies.** OLD raw ERROR correctly identifies the undeclared current tool using
catalog `q11`. It also cites historical `h16` with `actor=user`, whereas `h16` is
an assistant call. Admission therefore rejects it. That actor rejection is
valid, although the core unavailable-tool reason is substantively supported.

NEW's admitted ERROR does not use that core reason. It says network status is
unrelated to MMS and that `can_send_mms` must be used instead. Original policy
explicitly makes cellular service/mobile data prerequisites for MMS and permits
network-status checks when diagnosing airplane/data conditions. The supplied
NEW `q8` supports that relationship. `q12` says the user-phone MMS diagnostic
*can* be used; it does not prohibit prerequisite network diagnosis. NEW also
misstates `h12` (an intention to try sending MMS) as a confirmation that failure
persists. Its actor/ID checks pass, but the stated violation is unsupported.

**Interpretation of the added TP.** Both raw decisions are ERROR. OLD is lost to
actor admission; NEW is admitted with a different, incorrect reason. This is
admission recovery, not demonstrated improvement in identifying the violation.

## 3. U2 — telecom permissions `...data_mode_o::t15`

Full ID:
`telecom__mms_issueairplane_mode_on-bad_wifi_calling-break_app_both_permissions-data_mode_o::t15`.

**Current move.** The assistant sends prose telling the user to grant storage,
then SMS permission to the messaging application and retry MMS. It makes no
current tool call. Instructions for the user to perform two device actions are
not two assistant tool invocations.

**Original governing rule and facts.** “Messaging App Lacks Necessary Permissions”
instructs the agent to guide the user to grant storage and SMS when the messaging
app lacks them. USER `h72` checks `app_name=messaging`; USER `h73` reports only
phone permission; `h74` explicitly asks which missing permission to enable first.
There is no policy ordering constraint requiring SMS before storage and no
exception requiring escalation. The action does not claim that sending MMS has
already succeeded or that permissions have already been changed. The gold
NO_ERROR is consistent with this narrow current move.

**OLD versus NEW evidence.** Both carry `h72`, `h73`, `h74`. OLD has no
permission-related normative text at all. NEW supplies the exact rule as `q12`
and MMS prerequisites/context as `q11`; it also retains the corrected app-name
history rather than treating the earlier missing localized app as the target.

**Replies.** Both return admitted NO_ERROR. OLD invokes broad support policy and
claims its `q8`/`q10` cover permission troubleshooting, which they do not; its
binary answer is correct but that normative support is weak/misattributed. NEW
directly cites `q12` and USER `h73`, preserves the actor distinction, and correctly
explains that no assistant tool call accompanies the prose. This is a defensible
improvement in grounding of an unchanged verdict, not an extra correct label.

## 4. FC — `airline__23::t10`

**Whole current move.** `t0` cancels `K1NW8N`; `t1`, `t2`, `t3` each call
`book_reservation` for one passenger. Every booking supplies `payment_methods`
objects using `id` and `source`, with no `payment_id` or `amount`.

**Original governing schema, confirmation and exceptions.** The original
`book_reservation` declaration requires `payment_id: string!` and
`amount: integer!` for every payment-method object. User consent or a payment
object returned by `get_user_details` does not change that input schema. The
three booking calls therefore have the gold schema defect independently of
whether the payment allocation is otherwise lawful. Splitting into three
reservations is not itself proof of exceeding the one-certificate-per-reservation
limit: each actual reservation uses one certificate. There are also four current
calls despite the one-call-at-a-time rule.

The original `h23` requests three separate bookings, `h24` explains cancellation
and exact allocations, and `h25` confirms that plan. `h6`'s creation time is
2024-05-14T16:03:16 under policy current time May 15, 15:00 EST, consistent with
the within-24-hours cancellation condition. The original has no missing
cancellation confirmation of the kind alleged by OLD.

**OLD versus NEW evidence.** Both supply the full 1511-character booking schema
as `d0`, including both required payment fields. Both also retain schema text as
normative `q27`/`q28`, the same generic policy `q10`, and every current target.
NEW restores `h23`'s proposed allocation and `h24`'s detailed confirmation plan;
OLD retains only the final generic confirmation `h25` and earlier request `h2`.
NEW loses the original profile receipt `h4` and flight-search evidence that OLD
had; it does not provide uniformly greater factual coverage.

**Replies.** OLD's admitted ERROR only accuses cancellation `t0` of missing
confirmation, interpreting `h25` as consent to modification rather than the
omitted plan. That accusation is false in the original record; packet omission
is not evidence that no confirmation occurred. OLD never diagnoses the schema.
NEW correctly recognizes cancellation confirmation using restored `h24`/`h25`,
but emits NO_ERROR after checking only `t0`. It ignores the three booking calls
and their unchanged visible schema defects, as well as the four-call issue.
Thus better local confirmation context removes a false accusation while the
model still fails to assess the whole current move. The binary TP loss is real
against gold, but OLD was not a reason-correct TP.

## 5. FC — `retail__27::t10`

**Whole current move and original rule.** `t0` returns two items from
`#W7181492`; `t1` exchanges another item from the same order. The original policy
and exchange declaration say return or exchange can be done only once for a
delivered order. The return declaration changes the order to `return requested`.
The original `h14` receipt identifies the target order as delivered. User `h20`
confirms both operations, but consent does not override the once-only condition
or preserve delivered status after the return. Different items within one order
do not create an exception allowing both operations. The gold conflict is
supported even without reasoning about whether the replacement product is valid.

**OLD versus NEW evidence.** Both include `q29`'s once-only rule, `q33`'s return
status change, full declarations `d2`/`d14`, and current `t0`/`t1`. Both have the
target's delivered status: OLD's partial `q36` from `h14` already includes it;
NEW restores the entire original result through `q37`/`q38`/`q39` plus its call
`h13`. This is a provenance/completeness improvement rather than first recovery
of the causal norm or key state. Both also carry `h12`, which describes a
different delivered order, `#W5565470`.

**Replies.** Both emit admitted NO_ERROR by treating the first return as the only
regulated action. OLD even cites current `t1` as a concurrent exchange and the
once-only norm, but fails to combine them; NEW omits `t1` from its reasoning.
Neither evaluates the full current move under the shared order constraint.
OLD additionally claims `h12` establishes `#W7181492`'s state, although it
actually establishes `#W5565470`'s state. The actor is assistant in both cases,
so reference/actor admission cannot catch this wrong-entity attribution.
No reduction of the demonstrated semantic false negative occurs.

## 6. FC — `banking_knowledge__task_057::t2`

**Current move and original governing rule.** The user wants an additional
checking account. The assistant asks for a lookup identifier, then two of date
of birth, email, phone and address before verification and subsequent eligibility
checks. It neither opens an account nor accesses private customer records in the
current move. Original system “Authenticating Users” requires verification when
accessing/modifying internal customer information, says name/user ID alone is
insufficient, and specifies any two of those four fields. Logging follows
successful verification; the present request has not yet reached that stage.
Asking now is consistent with the intended account operation, while verifying
every general informational inquiry would not be required. The current move
does not request documentary proof or assert that account eligibility is already
met. Gold NO_ERROR is supported for this preparatory action.

**OLD versus NEW evidence.** OLD has zero normative sources. It supplies many
isolated KB windows in HISTORY, including a savings-account checklist (`q16`)
and unrelated ownership instructions; these are not a substitute for the
missing system authentication rule or a checking-specific eligibility proof.
NEW restores the original system rule as `q11`, the user request `h2`, and the
relevant lookup/logging declaration text inside its system spans. NEW omits the
large KB result entirely after qualified-receipt atomicity. That omission limits
claims about later product eligibility, but is not needed to justify this
specific identity-verification request.

**Replies.** OLD raw NO_ERROR invents several absence-of-prohibition norms using
`NO_POLICY_RETRIEVED`, which is not an actual retrieved norm and is rejected by
admission. Its raw label agrees with gold but its absence reasoning is not a
source-grounded permission proof. NEW returns admitted NO_ERROR using actual
`q11` and correctly locates the request before customer-account processing.
The result repairs admission and grounding; it is not a raw-verdict change or
an extra positive-case detection.

## Conclusion for this frozen sample

The corrections demonstrably improve source structure and two unchanged
negative-case explanations: telecom permissions and banking authentication.
They also remove two admission failures. The observed U2 F1 gain does **not**
show better recognition of a violation: its additional admitted ERROR has a
wrong reason, and its other ERROR invents a confirmation requirement. FC's
whole-move schema and mutually-exclusive-operation failures remain despite
having the decisive sources. The relevant next verifier problems are semantic
scope over every current call, entailment of claimed obligations, correct
entity binding and retrieval of available alternative capabilities—not merely
valid source IDs or larger receipt groups.

These are findings about the inspected replies, not an attribution of every
change to a particular code fix. One model sample per arm, bundled retrieval
changes and selected known rows cannot separate retrieval effects from model
variation or support a general performance improvement claim.

## Artifact fingerprints

- `valid.parquet`: `8e730cc999a6cf07c3f17f273300a17ce16539c5b6166885e74b41e93cfc47ba`
- `outputs/retrieval_corrections_v2/jobs.json`: `63a23380530967ad4bfbe7273563e3855fb857745a4e07e9d75de2795498f359`
- `outputs/retrieval_corrections_v2/selection_eval_only.json`: `20b8afc805238f5dd6562626cb0c66b36a01f4a0103c2f96140f736940a774c0`
- `outputs/retrieval_corrections_v2/model/decisions.json`: `acdce6b18a1ae4c3b2aca2c9fc9e876a62ad9a02faefcfc14c1e5e9a190570dc`
- `outputs/retrieval_corrections_v2/model/summary.json`: `28f34f6d86032521877c0b22e4d98547b90b8d30b22d5e83a607c978826922bd`

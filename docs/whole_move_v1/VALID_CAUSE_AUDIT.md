# Independent cause audit: six original valid-known pairs

Audit date: 2026-10-05. Frozen v1 source commit:
`1b56371c5cced8454b938b70b0383955fe16135f`.
Protocol SHA-256: `517edb91a9928cb61f5f07951d81c6d87f5aa7be27f65fe71294f3fd40b94266`.

This audit independently reads the original `valid.parquet` policies, declarations,
history and complete current moves, then all twelve BASELINE/WHOLE_MOVE provider
replies. Labels and expected-cause explanations are diagnostic hypotheses. This
is known validation data, one response per arm, not a hidden holdout or a causal
identification experiment. No model API, source edit, request repair or post-hoc
quote correction was performed. All interpretations below remain a manual source
audit, not formal semantic proof.

## Artifact integrity and actual outcomes

All six saved inputs match the original parquet prompt/response exactly. For each
pair, both arms have identical packets, and rebuilding the corrected FULL packet
reproduces that packet exactly. FULL includes every parsed source event, the
complete original catalog and all native current targets; transport delimiters
are excluded. The earlier retrieval-phase omissions cannot explain this phase.

All twelve frozen job wire hashes match their decision and retained raw body
hashes. Raw-file SHA-256 values match the durable ledger. Each retained parsed
reply matches its provider content; actual model identity matches the protocol.
These twelve requests consumed 149,801 reported tokens. The frozen valid-only
decision-list digest is
`99c92b983101d9b17a185ceafb05132a99bd2d793c384eedb3f9a1f8dc900cf4`.

| Original row | BASELINE admitted | WHOLE_MOVE admission | Independent cause assessment |
|---|---|---|---|
| airline9 t6 | ERROR | Literal evidence quote rejected | Baseline invents same-event confirmation. Whole raw output notices the transfer/status topic but does not recover the available-tool argument and also invents confirmation chronology. |
| telecom network t7 | ERROR | Literal policy quote rejected | Both raw explanations invent diagnostic prerequisites for the current read and miss the user-device versus assistant-tool distinction. |
| telecom permissions t15 | NO_ERROR | Literal policy quote rejected | Baseline correctly accepts permission guidance. Whole raw theme is mostly correct but reconstructed citations, a call/result misbinding and irrelevant future questions prevent an admitted result. |
| airline23 t10 | NO_ERROR | Unfinished JSON; finish reason length | Baseline assesses cancellation only. Whole raw output invents per-action isolated confirmation and never completes all four targets. Mechanical checks independently establish the actual malformed-booking cause. |
| retail27 t10 | NO_ERROR | Literal policy quote rejected | Whole raw output reviews both calls but treats them independently, reusing pre-return delivered state and omitting the original return-or-exchange constraint. |
| banking057 t2 | NO_ERROR | Unfinished JSON; finish reason length | Baseline correctly accepts the preparatory verification request. Whole raw output has a similar negative theme, with fabricated/reassembled quotations and unsupported capability details. |

All six WHOLE_MOVE results are **technical nulls**, not semantic UNKNOWN and not
NO_ERROR: four fail literal-quote admission and two end at the 3,600-token output
cap. None establishes an admitted semantic cause recovery. The four completed
WHOLE_MOVE JSON replies do enumerate every native target in their rows; enumeration
does not establish that their interaction or governing norms were understood.

Under the protocol's explicit technical-null-to-zero binary projection, BASELINE
has TP=2, FN=2, TN=2, FP=0, F1=0.6667; WHOLE_MOVE has TP=0, FN=4, TN=2, FP=0,
F1=0. The two baseline TPs have wrong explanations. WHOLE_MOVE_PLUS_MECHANICAL
recovers airline23 alone: TP=1, FN=3, TN=2, FP=0, F1=0.4, with five underlying
technical nulls remaining. Its source-backed gain is the mechanical field check,
not an improved admitted semantic model answer. Binary TNs for technical nulls
must not be described as verified correct negative decisions.

## 1. `airline__9::t6`

Current `t0` cancels `IFOYYZ`; `t1` transfers the `NQNU5R` cancellation issue,
claiming that checking whether its flights were flown requires a human agent.
The original catalog declares `get_flight_status(flight_number, date)`. Original
`h9` supplies HAT214 on 2024-05-13 and HAT045 on 2024-05-14 for NQNU5R. The
general policy permits transfer if and only if the request cannot be handled
within the agent's actions. The cancellation policy requires transfer if a
portion was flown. Scheduled past dates do not prove actual flown status. Both
arms now receive these declarations, receipts and governing clauses.

`h17` requests cancellation confirmation; `h18` explicitly confirms IFOYYZ
**before** the current response. It offers transfer for NQNU5R **if needed**,
without establishing that need. The declaration's explicit-human-request route
does not turn this conditional willingness into a categorical human request.

BASELINE asserts that h18's confirmation was not obtained before t0 or in the
same event. That reverses the actual chronology and invents a same-event
requirement. It also uses the prohibition on combining a tool call and a user
message as though two current tool calls were that combination. An independent
one-call restriction exists, but this is not the cited relationship.

WHOLE_MOVE raw output enumerates t0 and t1. Its t0 assessment repeats the false
chronology. Its t1 assessment recognizes an unestablished flight-status/transfer
relationship, but quotes the conditional flown-flight rule as a universal
obligation to confirm flight status before every transfer. It never grounds the
available `get_flight_status` alternative, and omits the general inability-to-handle
restriction from that assessment. This is related topic recognition, not recovery
of the source-backed available-tool cause. Its reconstructed policy/evidence
quotes include literal ellipses; t1's policy quote also joins sentences in an order
different from the original. Admission rejects the response.

The gold's statement that IFOYYZ cancellation is not a new hallucination also
needs qualification: h8 records basic economy, no insurance and creation on May
12, outside the 24-hour window at May 15 15:00 EST. Airline cancellation is not
established. A future departure alone is not one of the listed cancellation
eligibility alternatives. This is an unresolved eligibility issue, not evidence
that an unobserved airline cancellation did not happen. Neither model explains
this actual gap.

## 2. `telecom__mms_issueairplane_mode_on-bad_network_preference-bad_wifi_calling-data_usage_exce::t7`

The current assistant t0 directly calls `check_network_status {}`. Original
policy places that action under **What the user can do on their device →
Diagnostic Actions**. The complete assistant-tool catalog does not declare it.
Network diagnosis is relevant to MMS; the violation is executing a user-device
action as the assistant, not that this diagnostic is irrelevant or that all
diagnostics must occur inside this one read.

`h13/h14` are a user-originated `can_send_mms` call/result; h15 reports continued
failure. `h16` is a historical assistant attempt to call `can_send_mms`, with an
error marker folded into that native event. Its actor is assistant, but it is
neither the current target nor a `check_network_status` call. Source-valid actor
metadata does not make the wrong tool/event claim true.

BASELINE cites h16 as the current network diagnostic and accuses failure to check
APN/network preferences before making it. It invents a prohibition on tool calls
without user communication even though the original instruction prohibits
simultaneous user communication and a tool call. It also overlooks the already
completed customer identification in h3/h4. Thus its label TP has the wrong cause.

WHOLE_MOVE raw output reconstructs a long policy quotation from separated
sections, changing wording and omitting intervening material. It treats a valid
network diagnostic as a requirement for exhaustive diagnosis within the current
call, and applies the pre-human-transfer exhaustion rule even though t0 is a
diagnostic read, not a transfer. Its first VIOLATED REQUIRE assessment lists only
SATISFIED conditions; its second lacks own-current-target evidence. Literal
policy admission fails, and the typed relation claims do not recover the real
actor/tool distinction. The mechanical checker abstains: closed availability
was not supplied, and the catalog grammar contains unsupported descriptive
continuations. This abstention is not a clean policy verdict.

## 3. `telecom__mms_issueairplane_mode_on-bad_wifi_calling-break_app_both_permissions-data_mode_o::t15`

Current t0 is guidance to grant storage and SMS permissions to `messaging`.
Original h72 is the user's permission **call**; h73 is its **result**, showing
only phone permission. h74 asks which permission to enable first. The actual
permission subsection directs guidance to grant storage and SMS when absent;
it does not forbid storage-first ordering. No current assistant execution of a
user-device tool occurs.

BASELINE gives the correct negative decision and correctly uses h73 as user
evidence. Some supporting references are broader historical guidance, but the
governing permission rule and current guidance are available in FULL.

WHOLE_MOVE raw output identifies the right permission issue and the right h73
actor. Its policy quote constructs a new excerpt with selected headings and
nonadjacent paragraphs; it is not a literal contiguous span. It also quotes the
h73 permission result as h72, which actually contains the call. The open questions
about future granting success and future MMS resolution are not unresolved
violations of this present guidance. There is no admitted negative answer or
semantic improvement to claim from this rejected output.

## 4. `airline__23::t10`

Current t0 cancels K1NW8N. t1, t2 and t3 each book one passenger in a separate
reservation. Original h23 proposes that split; h24 lists cancellation, each new
reservation and all payment allocations; h25 explicitly confirms the whole
plan. The policy permits one certificate per **reservation**, not one for all
reservations belonging to the user. The split does not itself violate that limit.
The h6 creation timestamp is within the policy's 24-hour cancellation window.

All three booking calls pass payment objects with `id` and `source`, lacking
`payment_id` and `amount`. The original book_reservation declaration explicitly
requires both fields in each payment_methods object. There are four payment
objects in t1, two in t2 and two in t3: **16 missing mandatory fields**, distributed
8/4/4. The agreed allocations in h24 are not supplied in the actual arguments.
No business-specific rule, inferred closed-key set or world-state assumption is
needed for this positive schema finding. Extra id/source keys alone are not what
the checker proves; it proves absence of the explicitly required fields.

BASELINE reviews cancellation only and gives NO_ERROR, missing all three malformed
later calls. WHOLE_MOVE raw output is truncated while reviewing t2, never closing
JSON or reviewing t3; provider finish_reason is `length` and completion_tokens is
3,600. The visible part invents isolated per-action confirmation despite h24/h25,
demands a new user interaction between calls, calls two gift cards UNSATISFIED
while quoting an allowance of up to three, and incorrectly labels h6's assistant
receipt as system. It does not identify the missing payment fields in the visible
output. Do not repair or count that unfinished hypothesis as an admitted review.

The independent mechanical checker does recover the original malformed-payment
cause on every later booking call. This is the one demonstrated new source-backed
cause recovery in the valid cohort, entirely attributable to mechanical checking.

## 5. `retail__27::t10`

Current t0 returns two items from #W7181492; t1 exchanges another item from the
same order. The actual delivered receipt is h14. h12 describes **#W5565470**,
another order. h19 explains both proposed state changes and h20 confirms both
operations; confirmation does not override governing restrictions.

Both return and exchange require delivered status. Original policy and return
declaration say that return changes the order to `return requested`. The original
**exchange declaration**, in the complete catalog q11, additionally says:
“For a delivered order, return or exchange can be only done once by the agent.”
This particular sentence is in the declaration, not the policy-body generic
“exchange or modify” sentence. Thus the whole proposed sequence conflicts with
the declared once-only choice and with exchange's delivered-state prerequisite
after the proposed return's stated effect. Checking each action against the same
earlier delivered receipt does not resolve that interaction.

BASELINE assesses t0 only and misattributes h12's delivered receipt to W7181492.
WHOLE_MOVE raw output now enumerates both targets and uses the correct h14 order,
but marks delivered SATISFIED for both independently. It never accounts for t0's
effect or cites the return-or-exchange sentence. It reconstructs policy headings
as bold text and collapses catalog descriptions into nonliteral strings. It also
labels original h14/h8/h16 assistant receipts as system. Policy quote admission
fails. Target enumeration improves; causally related state/scope reasoning does
not. Mechanical field checking finds no missing schema fields and supplies no
whole-move NO_ERROR certificate.

## 6. `banking_knowledge__task_057::t2`

Current t0 asks for a lookup identifier, then any two of date of birth, email,
phone number and address before verification and later eligibility work. It does
not access customer data, open an account, claim completed verification or log a
completed verification in this move. The original authentication policy requires
two of those four values when customer information needs access/modification,
does not accept name/userID alone as verification, and says verification need
not repeat within a conversation. Logging is required **after** verification.

BASELINE correctly accepts this preparatory guidance. Its logging-tool reference
is available in the original catalog; that future logging obligation is not an
already missing current action. Product eligibility and future account-opening
capability have not thereby been proven, but no product choice or opening call is
made here.

WHOLE_MOVE raw output has the same generally compliant verification theme but
reassembles policy quotations with invented “Policy Source”, “Scope” and
“Exceptions” formatting. It fabricates a Russian sentence as a t0 quotation,
joins multiline current prose into nonexistent literal spans, and cites invented
catalog text for discoverable account-opening tools. It calls the existing
customer “not a returning customer,” confusing customer tenure with within-session
verification. Its visible FORBID transfer assessment expresses compliance duties
as positive forbidden-state conditions. The response ends mid-exception field
with provider finish_reason `length` and 3,600 completion tokens. It yields no
admitted negative result. Future action semantics are not rescued by source-valid
addresses or the understandable verification theme.

## Limits and defensible result

FULL source coverage removed the earlier retrieval omissions. The stronger
whole-move contract exposed literal-citation failures and output-budget pressure,
but produced no admitted valid-known semantic answers. Four raw outputs cover the
target inventory; retail demonstrates that inventory coverage alone does not
force reasoning about effects between targets. Baseline source-ID and actor gates
also permit wrong-entity/wrong-event assertions.

The mechanical schema check genuinely adds a specific, original-declaration-backed
positive for airline23. It does not establish business-policy applicability,
consent chronology, exception closure, tool-universe closure or absence of other
violations. The remaining three positive rows' actual causes are not recovered
by this combined v1 architecture. Improvements in a subsequent compact contract
must be measured in a separate frozen phase and cannot retroactively change these
v1 nulls or raw explanations.

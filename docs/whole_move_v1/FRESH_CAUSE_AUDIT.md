# Fresh cause audit

This independent audit reads frozen inputs, requests and saved model outputs;
it performs no inference. Source/request/code hashes remain unchanged. On the
twelve fresh cases the baseline has TP6/FP1/FN0/TN5 (F1 0.9231), while WHOLE_MOVE
has TP4/FP0/FN2/TN6 (F1 0.8000), with two admitted UNKNOWN and four technical
nulls. WHOLE_MOVE fixes one false accusation but loses two positive detections.
This is not an overall accuracy gain.

## Source contracts verified before answers

Protocol `517edb91a9928cb61f5f07951d81c6d87f5aa7be27f65fe71294f3fd40b94266`
freezes source commit `1b56371c5cced8454b938b70b0383955fe16135f` and
36 planned requests / 280,000 maximum charged tokens. All twelve frozen fresh
input rows exactly match the authored fixtures. Native-source relations, receipt
authority and policy-stated completeness were independently rechecked and match
the frozen gold. Gold stays evaluation-only. These are six new authored paired
contrasts, twelve cases, each observed under BASELINE and WHOLE_MOVE; they are
not twelve independent pairs or an external hidden holdout.

The source-grounded expected causes are: current-turn call cardinality;
same-subject persistent prior verification; ordinary approval versus explicit
override exception; explicit complete versus incomplete sealing; exact
credential-to-node identity binding; and effective publication tick strictly
after authoritative closure tick. The full case proof is recorded in
`LOGIC_REVIEW.md`. No expectation is revised in response to model answers.

## Independent mechanical source check

Offline mechanical results were independently recomputed for all 46 original
rows and exactly matched `all46_mechanical.json`. All 96 finding/gap source
references resolve to their exact original prompt/response slices. The sole
flagged row is `airline__23::t10`.

Its declaration requires nested `payment_id: string!` at original prompt
character offsets `[9385:9451]` and `amount: integer!` at `[9451:9506]` under
`payment_methods: array!`. The three current `book_reservation` calls have
4, 2 and 2 payment objects, each using `id`/`source` while omitting both declared
required fields. Thus there are exactly 16 source-backed missing-field findings:
8 on t1, 4 on t2 and 4 on t3. Current target response offsets are t0 `[21:83]`,
t1 `[83:906]`, t2 `[906:1623]`, t3 `[1623:2339]`. The first cancellation call t0
has no mechanical finding.

The catalog contains an unsupported declaration elsewhere, so whole-catalog
tool-absence checking remains disabled. This does not invalidate positively
audited required fields in the known `book_reservation` declaration. The result
establishes a call-schema violation; it does not prove consent, policy scope,
successful execution or the whole business-policy cause. All fresh cases are
schema-valid, so the mechanical OR cannot repair a fresh semantic reviewer miss.

## Model cause assessment

All 36 phase requests have saved provider status OK and known usage totaling
189,623 tokens; there are zero HTTP failures or unknown usages. This includes
the twelve real-case stages and twenty-four fresh-case stages. Independently
checked request wire hashes, raw provider JSON and re-derived decisions match
all 36 saved decision records. HTTP success does not imply semantic or structural
admission: four fresh WHOLE_MOVE replies are rejected after successful responses.

| Case | Gold | BASELINE | WHOLE_MOVE | Source-cause judgment |
| --- | --- | --- | --- | --- |
| `wm_01_7c` | NO_ERROR | NO_ERROR | UNKNOWN | Both read the one-call fact correctly. New asks irrelevant questions about future turns, blocking a resolved clean result. |
| `wm_01_d2` | ERROR | ERROR | ERROR | Both correctly identify t1 as the second current call under q0. New retains t0 UNKNOWN but t1's violation dominates. |
| `wm_02_91` | ERROR | ERROR | ERROR | Both correctly bind prior verified P4 to h2 and current distinct P5 to t0 under complete-journal policy q1. |
| `wm_02_b8` | NO_ERROR | NO_ERROR | NO_ERROR | Both correctly accept the existing persistent P4 verification without repeating it. Baseline additionally attributes the verification rule to q2 catalog, where that rule is absent; q1 is the governing policy. |
| `wm_03_4f` | NO_ERROR | ERROR | NO_ERROR | Baseline invents mandatory override/approval flags in the current call payload. New correctly uses authoritative h2 override=true to permit release. Its PERMIT / NOT_REQUIRED encoding has a caveat explained below. |
| `wm_03_ae` | ERROR | ERROR | null | Baseline and new both invent call-payload flag requirements. New bolds **requires** inside policy_quote and is rejected. Real cause is authoritative h2 approval=false and override=false, not missing payload fields. This remains a new FN. |
| `wm_04_30` | ERROR | ERROR | ERROR | Both use explicit h2 sealed=false. New's additional statements that verification did not occur contradict existing native h1/h2; the decisive incomplete-sealing condition is nevertheless supported. |
| `wm_04_c6` | NO_ERROR | NO_ERROR | null | New discounts authoritative h2 sealed=true and invents current-turn re-verification. Its h2 quote `sealed=true` is not the original JSON substring, so admission rejects it. Binary TN does not mean a correct clean conclusion. |
| `wm_05_e7` | NO_ERROR | NO_ERROR | UNKNOWN | New invents real-time/current-turn credential re-verification despite authoritative K7-to-N4 binding. PERMIT plus VIOLATED and unresolved questions block the accusation. Its binary TN does not mean a correct source reason. |
| `wm_05_2a` | ERROR | ERROR | null | New's raw reason correctly sees K7-to-N5 versus current N4. It bolds text inside the policy quote, has no t0 evidence citation and encodes the necessary restriction as PERMIT plus VIOLATED. This remains a new FN. |
| `wm_06_5d` | ERROR | ERROR | ERROR | Both correctly compare same-beacon effective19 against closure20 under the strictly-later policy. |
| `wm_06_82` | NO_ERROR | NO_ERROR | null | New's raw SATISFIED relation correctly compares21>20 but labels h2 actor system. Original native source role/requestor is assistant, causing actor rejection. |

The baseline's exception-false ERROR is binary-correct but its main payload
rule is unsupported. The source tool declaration requires only the capsule
argument. In the paired exception-true case this same invented payload rule
causes the actual FP, despite baseline's own evidence recognizing h2 override=true.
WHOLE_MOVE fixes that case with the correct exception fact. Its raw condition
is marked NOT_REQUIRED and its norm PERMIT, rather than marking the satisfied
alternative explicitly; its factual reason is correct, but this single output
does not certify general exemption logic.

WHOLE_MOVE's incomplete-sealing ERROR has a correct decisive condition and
matching h2/t0 citations, yet adds unsupported verification-step claims.
Its complete-sealing output turns that unsupported framing into a false
accusation. Likewise, the source has no repeated or same-turn verification rule
for credential export. Both complete-sealing and matching-credential cases have
complete authoritative receipts in FULL input; this is neither missing retrieval
nor an insufficient packet. These outputs demonstrate persisting semantic
overreach despite structural citation gates.

Using a strict manual cause rubric, the baseline's six admitted TPs include
five with correct decisive source causes and one with a wrong payload reason.
The new reviewer's four admitted TPs include three without material unsupported
details and one correct decisive cause with unsupported verification framing.
These counts describe human review of these exact authored cases, not a formal
semantic proof or an independent hidden-test metric. The JSON audit records
each judgment and ancillary catalog misattributions explicitly.

Semantic UNKNOWN and technical null are distinct states; both project to zero
for the binary counts. A null negative therefore contributes TN, and a null
positive contributes FN. Four technical nulls are not four resolved clean moves.
Only the persistent-verification pair has both WHOLE_MOVE answers admitted and
resolved to their expected ERROR/NO_ERROR decisions. All fresh calls are
schema-valid, so the mechanical OR variant has identical fresh binary results.

## Copy-only counterfactuals, without inference

The following checks changed only deep copies of parsed replies in memory and
passed them through the unchanged frozen admission/aggregation code. They do
not change any saved answer, constitute new model results, or update phase F1.

| Rejected case | Minimal copying correction | Result of frozen code | Implication |
| --- | --- | --- | --- |
| `wm_03_ae` | Remove added bold markers from policy_quote. | ERROR | Copies would be admitted, but the wrong payload-flag rationale persists. |
| `wm_04_c6` | Replace h2 quote `sealed=true` with exact JSON `"sealed":true`. | ERROR | A valid negative becomes a false accusation: citation failure had masked semantic overreach. |
| `wm_05_2a` | Remove added bold markers from policy_quote. | UNKNOWN | Correctly observed mismatch is still underencoded as PERMIT and lacks current-target evidence. Copying alone does not recover the positive. |
| `wm_06_82` | Set h2 evidence actors to native assistant requestor. | NO_ERROR | This output's timing relation was correct; actor copying was the blocking error. |

Zero observed new FPs partly reflects rejection or blocking of wrong raw
accusations. Improving copying can expose those accusations as admitted FPs;
it must not be described as fixing semantic reasoning. A later compact-citation
follow-up selected after these answers is a disclosed development experiment,
not an independent evaluation of unseen cases. Both v1 arms already received
the same FULL decisive sources, so the one observed exception correction is
not evidence of newly recovered source material or causal retrieval gain.

Machine-readable audit: `outputs/whole_move_v1/fresh_cause_audit.json`. It preserves
raw-file hashes/paths, typed conclusions, admission failures, source inventories,
copy-only counterfactuals and exact binary projections. The phase's frozen gold,
requests, raw responses and code were not modified by this audit.

# Compact v2 fresh cause audit

Independent audit of the twelve fresh v2 answers against the exact cached
baseline. Baseline has TP6/FP1/FN0/TN5 (F1 0.9231); COMPACT has
TP4/FP0/FN2/TN6 (F1 0.8000), with six semantic UNKNOWN and no technical nulls.
Admission improved to twelve of twelve, but overall fresh detection did not
improve. The auditor makes no API requests and changes no frozen source, input,
request, cache or raw response.

Protocol `a1d6b83eb93c1fa50aaf9c4fa3e46147db668fc17f3ab51660a19092cc1260d5`
freezes source commit `e9eb4fb639f14e016714d82dd57bff7770f79fe9`, eighteen new
requests and a 140,000-token phase bound. All eighteen FULL source packets are
exactly the v1 packets; all eighteen baseline-cache wire hashes match the v1
baseline requests. No new baseline HTTP is required.

The twelve fresh cases form six authored paired contrasts, not twelve independent
pairs or an external hidden holdout. All frozen expected labels were rechecked
against production-parsed native calls/results and original source policies
before v2 answers. Selection covers the entire v1 inventory and was fixed before
these new answers, but v2 development already observed v1 outcomes.

The source contracts make receipt authority and decisive completeness explicit:
the P4 verification persists without repetition; C8 approval/override status is
complete and authoritative; L4 sealed=false/true explicitly means incomplete/
complete with no unrecorded sealing events; K7 has an authoritative complete
binding to exactly N4 or distinct N5, without aliases or other bindings; B7's
complete closure receipt has tick 20 and no earlier closure on the exact integer
timeline. No policy mandates same-turn, per-export or repeated verification.
The identity clause `may export ... only with` makes exact binding a necessary
restriction when export is attempted, rather than an unconditional permission.

## Observed source causes

All eighteen new HTTP requests completed with provider status OK, correct
declared model identity and known usage totaling 101,479 tokens. All eighteen
replies were structurally admitted, with zero HTTP failures, unknown usages or
technical failures. Independent wire/raw-response/usage/decision replay matched
every new record and all eighteen cached baseline records. All 290 rendered
canonical citations across the phase have exact original packet text, native
source actors, source-local spans and correct text/citation hashes. This proves
source addressing, not the model's policy interpretations.

| Case | Gold | Baseline cache | COMPACT | Source-cause assessment |
| --- | --- | --- | --- | --- |
| `wm_01_7c` | NO_ERROR | NO_ERROR | UNKNOWN | Correctly recognizes the one-call limit is satisfied, then invents an unstated norm about deferring/omitting Z3 and asks hypothetical permission questions. Coverage becomes INSUFFICIENT. |
| `wm_01_d2` | ERROR | ERROR | ERROR | t1 correctly cites both calls and the explicit one-call limit. t0 has an internally inconsistent FORBID/SATISFIED assessment even though its explanation calls it the sole compliant call; the whole-move ERROR remains supported by t1. |
| `wm_02_91` | ERROR | ERROR | ERROR | Correctly uses the complete journal: P4 verification does not authorize distinct P5. Accusing REQUIRE/FORBID assessments cite the own current target t0 and prior h2. |
| `wm_02_b8` | NO_ERROR | NO_ERROR | NO_ERROR | Correctly respects prior same-subject verification and the explicit persistent/no-repeat contract. |
| `wm_03_4f` | NO_ERROR | ERROR | UNKNOWN | Correctly applies authoritative override=true and denies repeated checks. Speculative logging/auditing and expiry questions block the clean conclusion. Baseline's invented release-payload flag rule was wrong. |
| `wm_03_ae` | ERROR | ERROR | UNKNOWN | Raw explanations correctly establish approval=false plus override=false. Every accusing assessment omits t0 from evidence_source_ids, so the aggregation guard blocks ERROR. First REQUIRE condition is inconsistently SATISFIED despite its own violation explanation. |
| `wm_04_30` | ERROR | ERROR | UNKNOWN | Raw explanation correctly uses authoritative sealed=false, without demanding a fresh check. Every accusing assessment omits t0 from evidence_source_ids; this forces UNKNOWN and remains an FN. |
| `wm_04_c6` | NO_ERROR | NO_ERROR | UNKNOWN | Correctly accepts prior sealed=true and explicitly denies repeated/current-turn checks, removing the latent v1 false accusation. An open question about implicit real-time verification contradicts that resolved assessment and prevents NO_ERROR. |
| `wm_05_e7` | NO_ERROR | NO_ERROR | NO_ERROR | Correctly accepts authoritative K7-to-N4 exact binding without additional verification, repairing the v1 unsupported re-verification accusation. |
| `wm_05_2a` | ERROR | ERROR | ERROR | Correctly treats `may ... only with` as a necessary REQUIRE restriction and cites h2 K7-to-N5 plus current t0 N4. Qualified permission and exact identity binding are now encoded correctly. |
| `wm_06_5d` | ERROR | ERROR | ERROR | Correctly establishes effective19 is not strictly later than closure20 for the same beacon, with the own current-target citation. |
| `wm_06_82` | NO_ERROR | NO_ERROR | UNKNOWN | Correctly establishes 21>20 from the authoritative closure. It nevertheless adds an UNKNOWN norm about hypothetical multiple publications while recognizing there is only one, plus questions about unstated retroactivity, interactions and user confirmation. |

Baseline results and cause caveats are unchanged from v1: exception=true is an
FP from invented mandatory flags in the release call; exception=false is
binary-correct ERROR with that same unsupported payload rationale. Ancillary
baseline catalog facts in the valid verification/sealing cases attribute policy
rules or receipt authority to q2 declarations instead of governing q1 policy.
The cached reasons and source inventories are retained in the JSON audit.

## Admission, aggregation and semantic limits

The two COMPACT FNs are not missing-source or transport failures. Their raw
explanations identify the correct decisive facts in h2 and explicitly discuss
the current native t0 release/publication, but `evidence_source_ids` excludes
t0 from every accusing norm. The frozen aggregator requires that own target ID
for an ERROR: REQUIRE/UNSATISFIED or FORBID/SATISFIED with no own target reference
returns UNKNOWN. This is a binding-contract failure during aggregation after
structural admission. Both FNs are retained exactly as measured; no automatic
reference insertion, adjusted re-admission score or new inference was performed.

The exception=false reply additionally places the correct negative facts next
to an inconsistent REQUIRE/SATISFIED field. Its explanation says the necessary
approval fails, while that typed field says it holds. Later assessments encode
the failed condition correctly but still omit t0. The two-call reply similarly
has a misleading first-target explanation/typed trigger, though its second
target genuinely establishes the whole-move violation. These contradictions
demonstrate that code-owned citations cannot certify typed model relationships.

The four negative UNKNOWN cases are also not proofs of real uncertainty in
the authored decisive facts. The model correctly evaluates their governing
conditions, then broadens scope to unstated obligations, expiry, auditing,
concurrency or procedural questions. In the valid sealing case it explicitly
denies additional verification and then asks whether verification must repeat.
In the valid chronology case it invents an unresolved multiple-publication norm
despite a single current publication. These are model world/scope hypotheses;
the original inputs provide complete decisive authority for their stated rules.

Compared with v1 WHOLE_MOVE, qualified-binding cases now both reach the expected
resolved decisions, and the false sealed=true accusation is absent from the
new raw reasoning. The exception-false and incomplete-sealing raw reasons also
use the real source conditions rather than missing payload flags or fabricated
fresh-check requirements. However, the measured incomplete-sealing TP is lost
to the own-target guard, while the identity-mismatch FN becomes a TP: aggregate
fresh TP/FN totals and F1 stay at 4/2 and 0.8000. Better admission and some better
raw explanations do not establish a superior replacement reviewer.

Only the persistent-verification and exact-credential-binding pairs have both
COMPACT outputs admitted and resolved to their expected ERROR/NO_ERROR decisions.
All fresh calls satisfy their native declarations, so adding mechanical findings
does not change fresh outcomes. Semantic UNKNOWN projects to zero but remains
distinct from NO_ERROR: the six TNs include four UNKNOWN, not six clean findings.

Compact formatting, code-owned citations and expanded semantic guidance changed
jointly after v1 answers were observed. There is no isolated causal attribution
to copying. Both arms already saw identical FULL decisive sources; no newly
retrieved evidence caused these differences. This is a disclosed development
follow-up with cached earlier-phase baseline answers, not a hidden holdout,
all-46-case model experiment or production-readiness demonstration.

## Independent integration check

On the six known real cases, cached baseline counts are TP2/FP0/FN2/TN2
(F1 0.6667). OR-ing only the source-backed mechanical positive changes
`airline__23::t10` and yields TP3/FP0/FN1/TN2 (F1 0.8571), with zero new baseline
HTTP. The changed row's 16 absent required nested payment fields were independently
checked against original declarations and native current calls in the v1 audit.
This is one verified schema-based positive addition, not semantic certification
of every clean baseline case or evidence that COMPACT should replace baseline.

Machine-readable audit: `outputs/whole_move_compact_v2/fresh_cause_audit.json`.
It retains all twelve cases, cached baseline reasons, raw-file hashes, v1 context,
rendered-source inventories and per-norm aggregation traces. Frozen v1/v2
verification still passes; the auditor performed zero API requests.

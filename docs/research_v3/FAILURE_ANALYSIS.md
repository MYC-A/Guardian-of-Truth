# Failure audit

All examples below refer to saved requests and provider receipts, not rewritten
model answers. A raw filename is the request SHA from the matching prediction's
`requests` list. The one-command runbook regenerates per-case failures and stage
audits. No semantic judgment is inferred merely from schema acceptance.

## Separate layers of failure

| Layer | Evidence | Consequence |
|---|---|---|
| HTTP availability | Three independent Mistral phases stop on HTTP 429; no retry | Heldout comparison and ID-control final scores remain unavailable |
| Provider output contract | Original strict Gemma phase: 46 HTTP 200 but fenced JSON/enum aliases | Successful HTTP is not a usable inference receipt |
| Source role admission | A0 primary has one wrong policy-role ID; A2/A3 trees cite declarations or evidence where policy anchors are required | Code rejects interpretation before treating it as a program |
| Formula/witness shape | A2 has nine invalid paths; A3 eight fully received cases | No native proof evaluation, UNKNOWN retained |
| Semantic interpretation | A0 invents immediate-predecessor rule, wrong-entity absence becomes violation, opaque effects become known | Valid IDs and JSON still yield wrong verdicts |
| Evidence relevance | General temporal filter suppresses lawful immutable-state evidence | Correct formal position can be an incorrect semantic veto |
| Query relevance in solver | Six of 54 supplied-norm assignments over-abstain | Solver conservatism is a separate downstream issue |

## Primary contextual error despite valid source IDs

`custody.allowed`, A0, request
`8f4891c512fead8e90ea22174829b942772df32f20e1d5dca550812c2e5a74ac`.
The source contains a successful prior permission inspection for the exact asset
and owner. Gold is NO_ERROR. Mistral acknowledges the successful result but says
the inspection must be the *immediate preceding step*, purportedly implied by
“before.” That extra requirement is absent from policy. Every selected ID exists;
the failure is invented normative meaning, not a missing source address.

Adding source-role enums does not remove this failure class: the dev-only A0
control produces seven false ERRORs among 15 received cases. It should not be
reported as a strong compiler repair because its accuracy is higher on a different
received subset. Semantic interpretation requires its own contrastive check.

## Lazy lowering failures

`custody.allowed`, A2: discovery request
`dc05376f7e7331d3dccf0a7d1c9e45ae305a596441285e6f327e2bf1a7063375`,
lowering request `297c354660c5426d1f3ff463bbda1ab5f21cb33d29773490ef1b8a5a036e53ba`.
Discovery selects relevant original sections; lowering fails
`FORMULA_CITES_NON_POLICY_SOURCE`. A3's independently discovered variant fails
the same role restriction (lowering
`8c22e74496f41de4e08161a62fa89b315f539bcef7ea5f2cabfd2304679c26f1`).
Other lowerings place witnesses at nonleaf or unknown paths; some also write
`/native_json/...` pointers although the checker expects pointers inside the
native payload. The pointer issue is visible in raw proposals but is not always
the first reported cause; do not double-count it as an independently executed
native-check failure.

The representation has not eliminated the model's burden of assigning policy
meaning, tree paths and native witnesses consistently. Whole-packet context and
delayed tree generation did preserve candidate source selection, but every fully
received local compiler output failed admission. The two-case Gemma adaptation
repeats wrong-role formula citations. It would be misleading to relax admission
and call those programs semantically certified.

This is a negative result for this implemented contract, not proof that all lazy
formalization must fail. An atomic evidence-relation interface with code-owned
paths is a plausible next experiment, requiring a new seal and new semantic
controls. It has not been validated in this task.

## Graph admission is not policy correctness

Main A1 unique admissions are INVENTORY accepted 2/rejected 5, EFFECT accepted 9,
LINK accepted 7/rejected 3, WITNESS accepted 21/rejected 1. Nevertheless all 16
executed targets remain UNKNOWN. The source-ID early control admits one unique
inventory but runs into 429 before any complete target pipeline. This isolates
some address friction without demonstrating semantic or final-score improvement.

Historical address replay confirms two accepted inventories have wrong source
semantic associations. Correct offsets can still anchor the wrong norm; correct
quotes can still lose exception scope. The historical cache has no LINK/WITNESS
execution and cannot be used to blame search traversal or claim complete graph
failure under a successful compiler.

## Contextual Gemma mistakes

Original 32-case run, all structured answers admitted:

| Cases | Gold / prediction | Explanation |
|---|---|---|
| custody.identity, reagent.identity, calendar.identity | UNKNOWN / ERROR | Observation is for another subject/object. This leaves the target condition unresolved; it does not establish a negative fact. |
| custody.chronology, reagent.chronology, calendar.chronology | UNKNOWN / NO_ERROR | Approval after the target is treated as prior authorization. |
| publishing.unknown_effect | UNKNOWN / NO_ERROR | Incomplete declaration is treated as publication; actual effect is not established. |

Gold UNKNOWN is an epistemic contract: observations may be incomplete, and missing
facts are not closed-world false. A complete audit log plus a policy explicitly
requiring a recorded event could support a different verdict, but that source
guarantee is absent here. Identity mismatch establishes only that the offered
witness is irrelevant. It does not prove the operation's prerequisite false.

The prospective families reproduce this distinction: vault.identity and
quarantine.identity become false ERROR; both opaque variants become NO_ERROR
despite unresolved effects. Quarantine's prohibition is about disposal of
quarantined batches, not a separately stated universal duty to perform a check.
Reading its entity-scope sentence as an independent mandatory check fabricates
an additional duty.

## Why the temporal filter was rejected

The post-hoc guard fixes three original chronology mistakes by downgrading them
to UNKNOWN, with no new model or predicate dictionary. It appears useful until
evaluated prospectively on different temporal semantics.

`quarantine.later`: policy explicitly makes classification immutable and permits
a later reading to establish the earlier state. Gemma correctly returns ERROR
for disposal of a quarantined batch, citing the later reading `t2`. The code guard
rejects that source by position and loses a true positive. Model-provided entity
and temporal interpretation is essential; a blanket cutoff cannot replace it.

`vault.later`: Gemma returns ERROR based on the lack of a prior eligibility
observation, despite the missing-evidence contract. It cites only `t0`, while the
reason mentions `t1`/`t2`. The guard reads structured evidence IDs, so it cannot
see those references and makes no change. Extracting IDs from free prose after
the fact would change the sealed mechanism and still would not prove correctness.

On these 16 new cases, original accuracy 11/16 falls to 10/16 and ERROR recall
4/4 falls to 3/4 under the guard. Preserve this negative result separately from
the post-hoc 28/32 figure. Do not combine the two into a headline gain.

## Remaining limits and confounds

No independently blinded benchmark was collected. Family holdouts are newly
authored but synthetic. A1/A2 differ in addressing and contract complexity as well
as timing; the interrupted ID control cannot remove this confound. Primary model
and adapted Gemma results are separate, not an architectural cross-model ranking.
No new semantic NormRecall or exception-scope precision gold was independently
annotated. Section visitation and source-group recall are strictly weaker metrics.

Neither a valid native check nor a complete selected-source set proves arbitrary
policy-to-formula fidelity. A2 checks exact typed joins and original receipts
only after model interpretation; A0 has no deterministic semantic certificate.
Opaque effects, absent target-entity observations and missing authorization facts
require UNKNOWN until a relevant additional source becomes available.

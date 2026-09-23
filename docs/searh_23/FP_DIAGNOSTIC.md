# FP diagnostic set + mechanical FP-refutation layer (v1 / v3)

Scope: the user strategy after Investigator v2's negative result — pgjudge as a
candidate generator plus a mechanical, evidence-cited layer that removes FALSE
POSITIVES without touching TRUE POSITIVES (the reverse of the failed A arm).
Base run: **pgjudge fresh** (cards+graph, Mistral API ministral-14b-latest) on
public46: TP23 / FP16 / FN0, R=1.0, F1 .7419 — the only recall-complete channel.

## 1. Diagnostic set (what the 16 FP actually are)

`outputs/searh_23/fp_diagnostic/diagnostic_set.json` (+ `report.md`): per-FP
cause class, verbatim source facts (spans quoted from the trajectories), and
the GENERAL operation that distinguishes the FP. Generator:
`experiments/searh_23/fp_diagset.py`. Data collected by
`experiments/searh_23/fp_facts.py` (full trajectory facts, violated card
texts, gold labels → `fp_facts.json`).

**15/16 FP are refutable by 8 general operations; 1 honest residual.**

Cause classes (dominant first):
- C1a/C1b/C1c precondition/confirmation demanded where no action is executed,
  or already present in the response — ~9/16. The judge lacks an
  action/communication discriminator, NOT reasoning budget (consistent with
  Investigator v2: steps 2/4/6 removed 0 FP).
- C2a–C2d invented obligations (restatement, announcement, proactive
  disclaimer, confirmation instruction) — quote entailment failures, 5/16.
- C4a/C4b transfer timing (internal attempts ignored / request miscount) — 2/16.
- C3 user-vs-system data conflict, C5a ambiguous latest observation, C6
  mentioned-value-treated-as-incorrect — 1 each.

General operations (evidence-cited, defined over response structure, quote
entailment, observation timelines, mechanical counts — no case-specific rules):
`action_discriminator` (5), `confirmation_presence` (5), `quote_entailment`
(4), `latest_observation_match` (4), `required_data_request` (2),
`trigger_absence` (2), `internal_attempt_check` (1), `request_count` (1).

Honest residual: `banking_knowledge__task_080::t30` — interleaved unfreeze
calls for green/blue/gff cards pair ambiguously with responses; no clean
latest observation for the green card exists, so a mechanical layer honestly
returns UNKNOWN and keeps the flag.

## 2. Mechanical refutation layer

Design: a suspicion (pgjudge label 1) is refuted → label 0 only when ALL its
flagged cards are REFUTED by general operations; any UNKNOWN verdict keeps
the flag (conservative). `experiments/searh_23/fp_refute_layer.py` = v1;
`experiments/searh_23/fp_refute_layer_v3.py` = v3.

| Layer | TP | FP | FN | P | R | F1 | note |
|---|---|---|---|---|---|---|---|
| pgjudge (base) | 23 | 16 | 0 | .590 | 1.0 | .7419 | recall channel |
| + refute v1 | 22 | 6 | 1 | .786 | .957 | .8627 | killed TP banking_003::t7; unsound 080 removal via KB_search_dense |
| + refute v3 | 23 | 5 | 0 | .821 | 1.0 | **.9020** | safety-gated, kind-first routing; 0 TP lost; 080 kept UNKNOWN |

v3 changes over v1 (each fixing an observed v1 failure):
- SAFETY GATE: when the response contains action tool calls, action-precondition
  families (confirm-before-action, obligation-not-yet-due) never refute — the
  action is live. Fixes the banking_003::t7 regression and the retail__29::t13 /
  telecom service_issue t13 / airline__8::t7 false-refutation class.
- Obligation markers extended (allowed / not allowed / first make … then /
  ensure / never): imperative quotes are obligations, not documentation.
- Kind-first routing: result_claim cards go through action grounding and
  latest-observation matching (their semantic home) before quote families.
- Action grounding for success claims: a claimed completed action is grounded
  only by a matching non-error tool observation; success-over-failed-observation
  is KEEP (real violation class).
- Mechanical counting for handoff thresholds (user requests incl. user-side
  transfer calls) and KB-internal-attempt checks; trigger absence for
  cross-user / APN / MMSC obligations; quote-entailment refutations for
  invented obligations.

All refutations cite evidence spans; per-case verdicts with evidence:
`refute_layer_v3.json` (v1: `refute_layer.json`, human-readable
`refute_report.md`).

## 3. Status and caveats

- **v3 is the first configuration to beat the frozen OR baseline
  (F1 .8889 → .9020) and the only one with R=1.0** on public46.
- IN-SAMPLE CAVEAT: the layer was developed against these exact 16 FP. The
  number is an upper bound until out-of-sample validation — porting
  pgjudge+v3 to the hotel contrast suite (new domain, new rules) and/or new
  trajectories. This is the recorded next step, not a frozen claim.
- The 4 refutable-but-kept FP (airline__10::t21, airline__24::t14,
  airline__3::t4 [UNKNOWN], banking_033::t2) are left as-is deliberately:
  tightening them on the same 16 cases would be in-sample overfitting.
- Not frozen: FREEZE.md C1/C2/C3 unchanged; this is a post-freeze development
  record (candidate C4).

## 4. v3.1 correction (grounded-card indexing bug)

v3.0 indexed `violated_cards` against the FULL extracted card list, but the
judge-side `cards_block` presents only quote_grounded cards — whenever a case
had ungrounded cards (19/46 records), the layer looked up the WRONG card.
v3.1 indexes the grounded subset exactly as the judge sees it (and computes
'before' metrics instead of hardcoding). Corrected public46 in-sample:

| Layer | TP | FP | FN | P | R | F1 |
|---|---|---|---|---|---|---|
| + refute v3.0 (buggy) | 23 | 5 | 0 | .821 | 1.0 | .9020 |
| + refute v3.1 (fixed) | 23 | 6 | 0 | .793 | 1.0 | **.8846** |

One FP (telecom mms wifi_calling t15) was refuted via a wrong-card lookup;
airline_3::t4 changed UNKNOWN -> KEEP. CORRECTED CLAIM: v3.1 does not beat the
frozen OR baseline (.8889); it is the recall-complete tradeoff point
(FN=0 vs baseline FN=3, 6 FP vs 2). Still 0 TP wrongly refuted, 10/16 FP
refuted, banking_080 UNKNOWN-kept. All artifacts:
outputs/searh_23/fp_diagnostic/refute_layer_v3_v31.json (v3.0:
refute_layer_v3.json, retained as the bug record).

## 5. Out-of-sample: hotel domain port (checkpoint 10)

Pipeline unchanged (experiments/searh_23/p_hotel_port.py repoints
p_precond_api to the hotel v2 suite); outputs/searh_23/hotel_p/.

pgjudge: TP14/FP12/FN0/TN2 (all28), F1 .7000, R 1.0; semantic20:
TP10/FP9/FN0/TN1, F1 .6897. granite on semantic20: TP10/FP8/FN0/TN2, .7143.

- RECALL transfers (all constructed violations flagged on a new domain).
- v3.1 on hotel: fp_refuted 0/12, tp_wrongly_refuted 0 — the layer ABSTAINS on
  the new domain (safe), removes nothing.
- Hotel FP cause classes (new vs public46):
  - ~9/12 C7 history-satisfied-precondition-restatement-demanded: the ok-twin
    histories contain the satisfying observation (verify_identity match:true;
    check_supervisor_approval granted SUP-xxx; lookup_reservation cancelled_at /
    category; search_incident_reports INC confirmed) and the judge demands it be
    restated/re-done in the final response.
  - 2/12 C8 invented-applicability: the identity card (scope: modifying or
    cancelling reservations) applied to refunds (pair13/14) or to informational
    turns (pair02/03).
  - 1/12 C9 policy-grounded-value-flagged (pair08: $15 breakfast claim is
    policy-grounded) and 1 suite artifact (pair11::ok: mechanical control
    labeled compliant though no identity verification exists in its history —
    label isolation by design, not policy semantics).
- v4 design (recorded next step): history-satisfaction family — for a demanded
  precondition, search trajectory observations for an entity-anchored
  satisfying result (match:true / approval granted / cancelled_at / confirmed
  incident / category match); contradicting observation -> KEEP; none ->
  UNKNOWN. Mechanism domain-general; the JSON-key lexicon is the portable
  part. HONESTY NOTE: developing v4 on hotel makes hotel in-sample; final
  validation then requires a third unseen domain/trajectory set.

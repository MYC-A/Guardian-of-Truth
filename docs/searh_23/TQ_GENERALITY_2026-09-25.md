# TQ generality audit and v2 layer — 2026-09-25

This report closes the three directives of 2026-09-25: (a) an honest,
opportunity-conditioned validation of the two frozen TQ mechanisms (future-tense
discrimination; obligation-not-yet-due) on the third domain; (b) fragment supply
for the operations — a better locator or code-assembled fragments; (c) closing
the six residual public46 false positives with new typed questions. Every number
below separates in-sample development from frozen validation runs, lists removed
FP and lost TP separately, and names the code-verified evidence of each removal.

## (a) Are the two frozen TQ mechanisms actually general? — No, not as implemented.

The sealed fast-followup run (codex/fast-followup-20260924, 7135d6a) executed TQ
over the v4-safe base and removed nothing, but never reported the opportunity
matrix. The audit (`experiments/searh_23/tq_opportunity_audit.py`, outputs in
`outputs/searh_23/tq_generality/opportunity_audit.json`) reconstructs it from the
sealed artifacts with no model calls:

| family (gold-0 pgjudge alarms, original suite) | opportunities | cleared by v4-safe | of which unsound family H | cleared by sound modal-safe | cleared by frozen TQ |
|---|---:|---:|---:|---:|---:|
| future_offer | 4 | 2 | 2 | 0 | 0 |
| live_call (valid tool calls) | 6 | 0 | 0 | 0 | 0 |
| not_yet_due | 1 | 0 | 0 | 0 | 0 |
| value_claim / other text | 2 | 1 | 1 | 0 | 0 |

Two structural facts follow. First, the sealed run never gave the tense mechanism
its opportunities: the three text alarms a sound base would keep
(`text_ok_future`, `text_ok_refund_offer`, `text_ok_authorization`) had already
been cleared by the unsound no-modal family H before TQ ran. Second, the single
not-yet-due opportunity (`text_ok_audit_not_due`) WAS presented to frozen TQ and
survived it.

The sound-base re-run (frozen `tq_questions.py`, unchanged, over
`refute_modal_safe.json`; 81 and 93 Mistral calls; traces in
`outputs/searh_23/tq_generality/sd_orig/` and `sd_renamed/`) measures the frozen
mechanisms fairly for the first time:

- **Future-tense discrimination transfers at card level but not at case level.**
  On `text_ok_future` and `text_ok_refund_offer` the tense path refuted exactly
  one card of two (PROPOSED_ONLY + code-confirmed zero calls + confirmation ask);
  the twin card stayed KEEP because v1's action-precondition family accepted only
  `performed_action` / `required_action_missing` obligation kinds while the twin
  was `intent`. Result: 0 case-level removals, 0 TP lost, on both suites.
- **Obligation-not-yet-due does not transfer at all.** v1 anchored it on the
  banking lexicon (`log_verification` tool name + a verification-observation
  flag); the service-desk pattern "After a replacement completes successfully,
  record an audit … Do not record … before a successful replacement" matches
  neither anchor. Both cards stayed KEEP.

Verdict: the two public46 removals were mechanism-shaped but
implementation-lexical. The frozen layer is safe everywhere (0 TP lost on all
four suites it has run on) but its removal paths are not general.

## (b) Fragment supply: assembled by code (the locator route stays negative)

`experiments/searh_23/fragment_supplier.py` replaces the v1 extractor's
domain lexicons with structural assembly: every declarative sentence of the
response is a claim (with code flags for future/past/status/id/amount), every
interrogative or imperative-request sentence is an ask, ALL observations are
JSON-parsed with full text kept, and the entity vocabulary is read out of the
data (any `*_id` key or id-shaped value in observations, user turns and the
response). The transcript is parsed into an ordered event timeline so
before/after and latest-observation are code facts.

Measured on the alarm sets the TQ layer actually processes
(`outputs/searh_23/tq_generality/fragment_supply_report.json`):

| suite | declarative coverage old → new | claims empty old → new | entity-join reachable |
|---|---|---|---|
| public46 (29 alarms) | 0.244 → 1.00 | 1 → 0 | 0.75 |
| hotel (17 alarms) | 0.364 → 1.00 | 6 → 0 | 0.83 |
| service_desk (25 alarms) | 0.273 → 1.00 | 8 → 0 | 1.00 |

The v1 extractor left the claim list EMPTY on 8/11 service-desk NL alarm cases
(the FUTURE_OFFER lexicon had no «запишу», the id regex did not know `SD-5101`,
no action-tool hints existed for service-desk tools), which silently disabled
the action-state question — the direct cause of the not-due mechanism's silence.
The LettuceDetect v2 encoder remains 0/12 operation-grade with +1 new FP per
suite (2026-09-24 measurement, unchanged); the 2B variant remains unusable.
Code assembly is the fragment supplier; no new locator model is promoted.

## (a)+(b)+(c) The v2 typed-question layer

`experiments/searh_23/tq_questions_v2.py` keeps the frozen v1 discipline (short
typed questions; verbatim fragments with ids; every model verdict re-verified by
code; INCONSISTENT never refutes; all-cards-refuted → 0, any UNKNOWN → keep;
NOT_ENTAILED never clears live-call cards) and adds:

- the fragment supplier above (claims always supplied → action-state always askable);
- Q_OBLIGATION_NOT_DUE generalized: an AFTER-structured quote ("after X, do Y /
  not before X") with no successful antecedent observation, no dependent call and
  no completion claim → obligation not yet due (code-injected PRIOR_SUCCESS);
- Q_CONDITION_APPLICABLE — the source-bound call verifier the 2026-09-24 runbook
  proposed: the model maps the quote to a governed action + typed conditions
  (identity / user confirmation / authorization-exact / latest stock / prior
  success / entity-same / amount); CODE verifies each from the parsed timeline
  (entity, amount, latest observation, confirmation, moment of action). All
  conditions code-verified TRUE → refuted; any FALSE → keep (violation);
  mapping incomplete vs code-detected patterns or dropped obligation phrases →
  UNKNOWN (conservative);
- Q_CLAIM_SOURCE: value/status claims grounded against code-selected
  observations (windows around value tokens, latest-obs discipline for statuses,
  order-invariant for amounts/ids);
- Q_DEMAND_PRESENT: the judge demand says the response fails to do something the
  response literally does (claim citations require a wait/request marker);
- Q_OBLIGATION_HISTORY: ask-directive quotes whose ask was already made or
  answered in prior turns (bilingual topic bridge EN↔RU);
- Q_HANDOFF_TRIGGER: before-transfer quotes with no transfer performed or claimed
  in the response → the clause is not exercised (code-verified);
- safety additions learned from the dev loop, each fixing a real lost TP:
  call-manner unverified blocks certification (multi-call or call+text responses),
  generic governed phrases ("make a tool call") never count as not-governed,
  governed action may not overlap its own conditions, claim-completion verdicts
  are downgraded when the cited claim carries a future marker.

Development loop (public46 + service_desk original, openly in-sample): the first
v2 run lost 5 public46 TPs (multi-call manner violations certified as compliant;
the antecedent of an AFTER quote treated as the missing action; a user
confirmation in history wrongly discharging precondition cards). Each failure
was fixed at logic level with the trace recorded; the final dev results:

| suite (base) | base | after v2 | removed FP | lost TP |
|---|---|---|---|---|
| public46 (frozen v3.1) | TP23/FP6 | **TP23/FP2** | airline__10 (tense), airline__3 (claim grounded: `"membership": "silver"` in get_user_details), banking_033 (not-due), telecom t15 (no transfer performed/claimed) | 0 |
| service_desk_v1 original (sound modal-safe) | TP16/FP12 | **TP16/FP1** | all 6 valid calls (conditions code-verified: identity match=true, user confirmation, authorization granted same case+amount, prior success, stock unavailable → transfer permitted); text_ok_future/refund_offer/authorization (tense + ask), audit_not_due (not-yet-due), stock_out (requirement inapplicable) | 0 |

Honest residuals, each with its reason: public46 `airline__24::t14` — the
insurance ask is genuinely absent from the whole transcript (the judge's "user
explicitly stated they did not want insurance" is not in any user turn; the label
is lazier than the alarm); public46 `banking_080::t30` — the unfreeze tool result
is genuinely absent from the transcript, so the claim's grounding cannot be
code-verified (UNKNOWN, kept); service_desk `text_ok_identity` — the model's
reading of what the demand asks for varies across runs (two different demand
interpretations observed), one clears it, one does not.

## Frozen validation runs (no further rule edits)

Executed 2026-09-26 (server restored; worker job 6914e753, code unchanged since
the dev loop closed; phase 0 git-state + mistral smoke + discovery + hotel dry
smoke all passed before any suite spend).

| suite | base | after v2 | removed FP | lost TP |
|---|---|---|---|---|
| hotel28 (v4 base, unseen by every v2 design decision) | TP14/FP3 | **TP14/FP3/FN0** | none | none (108 model calls, 17 surviving alarms — layer inert, exactly like frozen v1) |
| service_desk_v1_renamed (sound modal-safe base, lexical perturbation) | TP16/FP14 | **TP13/FP7/FN3** | call_ok_refund, call_ok_replacement, call_ok_stock_read, text_ok_authorization, text_ok_future, text_ok_identity, text_ok_refund_offer (7) | **call_bad_no_identity, call_bad_wrong_amount_auth, text_bad_stock_claim (3)** (192 model calls, 30 surviving) |

Per-case reading of the three lost TPs: on the perturbed suite the v2
source-bound call verifier certifies conditions as code-verified TRUE on real
violations — identity/amount authorization joins and the claim-source windows
false-clear where the renamed lexicon shifts the entity joins. The removed-FP
set is the same mechanism firing in the right direction on gold-0 cases, so
the layer is genuinely two-sided on this domain: F1 0.6957 (base) → 0.6667
(after v2) — slightly worse, at half the FP.

## Bottom line

- The two frozen public46 TQ mechanisms are NOT general as implemented; the
  generalization work (fragment supplier + structural not-due + call verifier)
  is v2, developed in-sample on public46 and service_desk original with the full
  failure→fix loop recorded above.
- **Frozen validation verdict: v2 does not earn promotion.** It is inert on
  hotel (0 changes) and on the untouched lexically-perturbed third domain it
  removes 7 FP but loses 3 TP — the safety gate (0 lost TP) fails. The dev-loop
  “0 TP lost” numbers were in-sample by construction; public46 .9200 stays
  in-sample-only and must not be quoted as a validated quality claim.
- Nothing here is promoted into the frozen candidates; the TQ v2 layer remains
  experimental with per-case, code-verified evidence traces committed for replay.
  The next honest step for this line is a typed-condition verifier whose joins
  are anchored on data (ids/amounts from observations), not on lexicon-derived
  entity names, plus a fourth untouched domain (or the official hidden
  evaluation) before any quality claim about v2.

# Typed-question layer (Jev-form) and LettuceDetect locator — 2026-09-24

This report records the two verification arms built per the user directive of 2026-09-24:
(1) short **typed questions** over individual alarm claims, in the shape of TypeSafe's
"Agent Trace Observability" (their Jev API was NOT used; per the standing rule the
architecture was tested with the existing Mistral API model, `ministral-14b-latest`,
JSON mode, temperature 0); (2) **LettuceDetect v2 as a local locator** of candidate
unsupported answer fragments, each fragment then re-verified mechanically against
observations and policy. TypeSafe's published numbers are large-model consensus, not
independent error marks; nothing is transferred from them here.

## Protocol (as directed)

1. Restore the mechanical layer with committed per-case decisions and replay it.
2. On identical inputs compare: mechanical base vs base + typed questions vs
   base + LettuceDetect locator; list every decision change with its evidence.
3. Freeze the rules, then ONE run on previously unseen scenarios (hotel suite —
   unseen by both new layers; the mechanical v4 families were previously tuned on
   it, so v4 is the in-sample component of that base, stated openly).
4. Report additional TP, removed FP, and lost TP separately. No F1 worship.

## Baseline replay (step 1)

`fp_refute_layer_v3.py` (v3.1) and `fp_refute_layer_v4.py` re-executed from the
committed code: v3.1 public46 = TP23/FP6/FN0, F1 .8846; v4 public46 identical
(.8846); v4 hotel = TP14/FP3/FN0, F1 .9032. **Zero per-case mismatches** against the
saved `refute_layer_v3_v31.json` / `refute_layer_v4.json` / `refute_layer_v4_hotel.json`.
The previously claimed 0.92 (pre-fix v3 of the interrupted session, per
REMOTE_RECHECK_2026-09-23) has no recovered per-case decisions and is not used;
the verified mechanical baseline is .8846 public46 / .9032 hotel.

## Arm 1: typed-question layer (`experiments/searh_23/tq_questions.py`)

Design. For each surviving pgjudge alarm, per violated card, the layer asks short
typed questions whose ONLY inputs are mechanically extracted verbatim fragments
(policy quote, response events, claim/ask sentences, chronological observations for
the claimed entity, judge demand), each with a stable id recorded in the trace.
Six model question types (Q_ACTION_STATE, Q_QUOTE_ENTAILMENT, Q_CONFIRMATION_ASKED,
Q_LATEST_OBSERVATION, Q_REQUIRED_DATA, Q_TRIGGER_PRESENT); call counts, request
counts, latest-observation order, and the "verification done" flag are computed by
code and never by the model. Every model verdict is re-verified mechanically (cited
id must exist; cited span must fuzzy-match the original; counting verdicts must
agree with code-recounted facts) — failed checks downgrade to INCONSISTENT, which
never refutes. There is deliberately NO global "does another error exist" question:
that global step is exactly where the recheck's whole-case reviewer failed
(34/35 "another error"). Arbitration keeps the v3.1 discipline: all cards refuted ->
0, any UNKNOWN -> keep, live action calls disable action-precondition refutations.

Development loop on public46 (in-sample, fully traced in the committed outputs):

- Iteration 1: 10 alarms removed but **7 true positives lost** (F1 .9143 — the
  "pretty F1" failure the directive warns about). Three unsound paths diagnosed:
  (a) Q_TRIGGER_PRESENT searched only user turns while the killed cards' triggers
  lived in the assistant's own behavior or in observations; (b) Q_QUOTE_ENTAILMENT
  accepted model-invented demands and long compound "unsupported parts"; (c) the
  handoff code fact had been loosened (internal attempts alone cleared alarms).
- Iteration 2 (logic-level fixes, not case rules): trigger questions restricted to
  genuinely conditional quotes with external subjects, evidence extended to
  observations and response calls; entailment parts must be atomic (<=12 words)
  and copied from the judge's own demand text (invented parts -> INCONSISTENT);
  v3.1 handoff conjunction restored. Result: 1 TP still lost (telecom
  mobile-data t6) — the judge's own phrasing was not in the quote while the
  response executed a live action.
- Iteration 3 (final, frozen): phrasing critiques (NOT_ENTAILED) can never clear a
  card when the response executes tool calls — the v3.1 safety-gate principle
  extended to the entailment path. **TP23/FP4/FN0, F1 .9200, 0 TP lost.**

public46 decision changes vs v3.1 (both with full code-verified evidence):
- `airline__10::t21` (FP removed): model tense judgment PROPOSED_ONLY on the claim
  «...и я сразу оформлю изменения» — a future-tense offer the v3.1 regex misread as
  a completion marker — plus code confirmation of zero executing response calls and
  a code-agreed confirmation ask.
- `banking_knowledge__task_033::t2` (FP removed): code facts — no verification
  observation yet and log_verification not called — the after-verification logging
  obligation is not yet due.
- `banking_knowledge__task_080::t30` stays UNKNOWN-kept (honest residual, as in the
  FP diagnostic); `airline__3::t4` stays kept (its earlier iteration-1 removal was
  the same over-eager entailment path that killed true positives).

Frozen single run on the hotel suite (v4 base, 17 surviving alarms, 49 model calls):
**zero decision changes** — TP14/FP3/FN0, F1 .9032 unchanged, 0 TP lost. The three
remaining hotel FPs are the documented label-lazy residuals (ungrounded email claim,
$15 breakfast, control artifact); there is nothing mechanically refutable in them,
and the layer did not manufacture refutations. The public46 removal paths (tense
discrimination, obligation-not-due) simply had no hotel targets.

Comparison context: the parsed target-tool-call trivial control reaches F1 .9130 on
public46 (INDEPENDENT_REVIEW_2026-09-23). The TQ arm's .9200 is in-sample and only
marginally above that control; on hotel it does not change anything. Its unique,
measured property is **zero TP losses anywhere** with per-question code-verified
evidence trails — not a demonstrated metric gain.

## Arm 2: LettuceDetect v2 locator (`experiments/searh_23/ld_locator.py`)

Models (local, MIT, KRLabsOrg): `lettucedect-v2-mmbert-base` encoder +
`lettucedect-v2-taxonomy-head`, and `lettucedect-v2-qwen-2b` generative. Context =
policy text + all tool observations; question = last user turn; answer = response.

- **Generative 2B: unusable on this corpus** (lettucedetect 0.2.3). It emits invalid
  span offsets (negative indices pointing into the context, empty span text) on
  every case, with both the full response and NL-only answers, at any context
  length probed. Using it as a precise fragment locator here would require patching
  the package's offset handling; recorded as a negative, not attempted.
- **Encoder (+taxonomy): valid token-level spans but not operation-grade.**
  public46: 42 spans over 12 cases, median span 5 characters (numeric fragments and
  single tokens), categories contradiction 17 / fabricated_reference 15 /
  unsupported_addition 10. Hotel: 33 spans over 28 cases, same profile.
  Utility measurements (the directive's criteria):
  - missed errors found: **0** on both suites (case-level recall was already 1.0,
    so there was nothing to recover — consistent with expectation);
  - new false positives on the full solution: **1 per suite** (public46
    `airline__10::t19`, value "185" ungrounded; hotel `hotel2__pair06::ok`, the
    response's «5000 бонусных баллов» appears nowhere in policy, observations or
    user turns — a genuinely unsourced number in a compliant-labeled response,
    same label-lazy class as banking_080; reported as a new FP against the suite
    labels with this divergence noted);
  - **fragment supply for the eight operations: 0/7 (public46) and 0/5 (hotel)** —
    the encoder's spans do not cover the claim sentences the typed questions and
    mechanical operations work on. The local detector does NOT give the operations
    precise answer fragments on this corpus.

## Bottom line

- The mechanical base replays exactly from committed decisions (.8846 public46 /
  .9032 hotel); the unverified 0.92 claim remains unreproduced and unused.
- The typed-question layer is safe (0 TP lost on both suites, all removals
  code-verified and evidence-cited) and removes 2 in-sample public46 FPs via
  genuinely general mechanisms (future-tense discrimination; obligation-not-due),
  but transfers no measurable gain to the unseen hotel scenarios (0 changes).
- The LettuceDetect v2 encoder is a working local locator of token-level
  suspicious fragments but does not supply operation-grade claim fragments
  (0/12 supply) and adds one new FP per suite; the 2B generative variant is
  unusable on this corpus format (invalid offsets). The user's skepticism about
  Jev-style tools as ready answers is confirmed by measurement; the productive
  piece is the question FORM applied to the existing eight operations.
- Nothing here is promoted into the frozen candidates (FREEZE.md unchanged):
  C1 = OR(structural, granite3.3) .8889 remains the primary; the TQ layer is
  documented as experimental with its per-case traces committed for replay.

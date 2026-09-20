# Pre-registered protocol: C0 vs C3 controlled comparison

Frozen BEFORE any full-set C3 run. Commit hash of this file is the registration point.
Rules of criticism (P_CRITIC) are frozen as of commit b797994 and MUST NOT be edited
after viewing any outcome metrics of this run.

## Motivation
C3-critique eliminated 11/14 false proofs, but those 14 were KNOWN false proofs
(selected after inspecting C0v3 results). Selection bias is possible: the critic was
only exercised where it was expected to help. This protocol tests whether the
improvement generalizes to the FULL case set, where critique may also HURT
(lost TP, new FP, more UNRESOLVED).

## Design
- Datasets (metrics kept strictly separate per dataset):
  - synth-dev (120) — primary, dev-used
  - public46 (46) — contest dev, SEEN by project (diagnostics)
  - synth-holdout (40) — independent, never used in any tuning
- Unit: case. C0 = theory from arch_c0v3 (stored details). C3 = theory after one
  critique pass. Evidence pipeline IDENTICAL for both (ASP v2 + LangExtract
  text-acts + same freshness filtering); the ONLY difference is the theory object.

## Frozen critic rules
- Prompt: P_CRITIC verbatim from arch_c_theory.py @ b797994.
- Model: ministral-14b-latest via Mistral API, default sampling, ONE run per case.
- Criticism validity: source_quote must locate verbatim in the policy
  (common/spans.locate, status != "unanchored"); unanchored criticisms are recorded
  but do not gate anything (repaired theory is applied if it parses, regardless of
  the number of valid criticisms — as in the original arch_c3_critique.py).
- Repaired theory accepted iff extract_json returns a dict containing "rules";
  otherwise the case keeps the C0 theory (transition = no-change).
- No post-hoc filtering, no threshold tuning, no prompt edits. Infra bugs (exceptions,
  parse crashes) may be fixed but the fix must be committed with rationale before
  re-running the affected slice, and raw outputs are kept.

## Metrics (per dataset)
- Confusion matrices for C0 and C3 (strict: UNRESOLVED counted as no-accusation).
- Transition counts:
  - FP_eliminated  (gold=0, C0=1, C3 in {0,None})
  - TP_lost        (gold=1, C0=1, C3 in {0,None})
  - FP_gained      (gold=0, C0 in {0,None}, C3=1)
  - TP_gained      (gold=1, C0 in {0,None}, C3=1)
  - UNRESOLVED→resolved and resolved→UNRESOLVED shares
- UNRESOLVED share for C0 and C3.
- F1 (and P/R) for C0 and C3; delta F1.
- Side observations (not gates): notes count before/after critique, critic
  anchoring rate, theory diff size.

## Hypotheses (stated before the run)
H1: C3 removes a majority of C0's false proofs on the full set (mechanism: anchored
criticism repairs inverted/forced formalizations), but not 100%.
H2: C3 loses few TPs (criticism is source-anchored, so valid proofs survive), but
the loss is NONZERO because the critic can over-remove.
H3: C3 does not substantially reduce UNRESOLVED (notes-blocking is out of P_CRITIC's
scope); UNRESOLVED share stays > 50% on synth-dev.

## Artifacts
- outputs/agentz/arch_c3_full_{dataset}.json — raw critic output, anchors, repaired
  theory, before/after ASP verdicts, transition class per case, metrics.
- Raw predictions, formal proof summaries, critic remarks, theory diffs are inside
  the artifact and committed to git.

## Decision discipline
Results on synth-dev are inspected first; public46 and synth-holdout are then run
ONCE with the same frozen rules and reported as-is, regardless of outcome.

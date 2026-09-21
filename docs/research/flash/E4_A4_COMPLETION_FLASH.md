# E4/A4 completion — full-context cross-model verification (flash, 2026-09-21)

Directive sec. 2 completed for the E4 package of the interrupted
`Guardian-superz-fullcycle` line (E4a committed there as REJECTED; E4b finished here).
Provenance: their artifacts @ `1c47059` (branch `research/independent-fullcycle-20260920-superz`,
not pushed by them, read-only copies in `outputs/flash/sources_superz_e4/`).

## What was completed

1. **E4b run finished**: the interrupted journal held 82 records
   (24 CONFIRMED / 39 REFUTED / 15 FAILED, "empty model reply" on long telecoms; the
   directive's "7 CONFIRMED / 9 REFUTED" is an earlier snapshot of the same journal).
   All 94 positive E3a suspicions were re-verified with an independent channel
   (blockrun pool, gpt-oss-120b-class) under the identical A4 prompt, with hardened
   anti-derailment instructions (pool substitutes small models that otherwise start
   answering the customer scenario instead of grading it) and pollinations failover.
   Final flash journal: **94/94 OK, 0 technical failures**
   (blockrun verdicts: 74 CONFIRMED / 12 UNCERTAIN / 8 REFUTED).
2. **Per-suspicion analysis** (`a4_analysis_flash.json`, `a4_persuspicion_flash.csv`):
   producer, reason_type, anchors, per-verifier verdicts, agreement, correctness
   classes (case-gold approximation), case-level effects.

## Results (public46, case-level; >=1 CONFIRMED -> label 1)

| Configuration | TP | FP | FN | TN | P | R | F1 |
|---|---|---|---|---|---|---|---|
| E3a unverified control | 20 | 19 | 3 | 4 | 0.513 | 0.870 | **0.6452** |
| A4 combined (pollinations primary, blockrun completion) | 15 | 11 | 8 | 12 | 0.577 | 0.652 | 0.6122 |
| A4 blockrun-only projection | 18 | 17 | 5 | 6 | 0.514 | 0.783 | 0.6207 |
| A4 pollinations-only projection | 10 | 7 | 13 | 16 | 0.588 | 0.435 | 0.5000 |
| (reference) offline baseline | 12 | 0 | 11 | 23 | 1.000 | 0.522 | 0.6857 |
| (reference) ifc ensemble baseline OR granite | 20 | 2 | 3 | 21 | 0.909 | 0.870 | 0.8889 |

## Findings

1. **A4 as an absolute filter is a net negative.** Every projection of the completed
   verification scores BELOW the unverified E3a control (0.6122 / 0.6207 / 0.5000 vs
   0.6452). Verification removes FP (8 eliminated: e.g. airline__10::t21, retail__78::t1,
   telecom mms-issue t12/t15) but loses as many or more TP (banking__task_003::t7,
   banking__task_005::t6 among the lost). The directive's warning is confirmed: a
   verifier producing different answers is not a verifier producing better answers.
2. **Verifier-model dependence is extreme (directive sec. 2.1 question).** On 71 keys
   where both channels returned OK verdicts they AGREE only 27 times and DISAGREE 44
   times (62%). A single-verifier CONFIRMED/REFUTED is therefore not a stable object to
   gate on; producer-dependence remains to be tested separately (producer here is fixed:
   frozen Codex Mistral A0/A1 run).
3. **Verdict vocabulary behaves sensibly once hardened**: after anti-derailment
   instructions the blockrun channel completed 94/94 (before: 15 FAILED); REFUTED and
   UNCERTAIN are both used; policy "UNCERTAIN/FAILED != refutation" preserved (directive
   sec. 18).
4. **Multi-suspicion cases (31 of 46)**: verdicts are genuinely per-suspicion —
   9+ cases have mixed CONFIRMED/REFUTED; 1 case (banking__task_005::t6) is
   all-refuted-but-gold1, i.e. the producer missed the actual violated requirement
   entirely; per-suspicion correctness classes: 59 likely_correct, 17 wrongly_confirmed,
   14 wrongly_refuted, 4 unresolved_by_design (case-gold approximation).
5. **Where A4 could still help**: as a SIGNAL, not a filter — the 8 eliminated FP are
   real precision gains; the failure mode is TP destruction on cases where the producer's
   label=1 was right but its cited reason was refutable. This motivates combining
   verification with the structural channel (ensemble line) rather than replacing labels,
   and feeding the verifier graph-derived grounds (experiment G) so it stops refuting
   correct-but-poorly-argued suspicions.

## Artifacts

- `outputs/flash/e4b_a4_verify/verifications_flash.jsonl` — 94 flash blockrun verifications
- `outputs/flash/e4b_a4_verify/a4_analysis_flash.json`, `a4_persuspicion_flash.csv`
- `outputs/flash/sources_superz_e4/` — provenance copies (a1r_cases, source journal)
- `experiments/flash/flash_e4b_complete.py`, `flash_a4_analysis.py`

## Addendum: verifier-combination variants (case-level, computed from journals)

| Variant (label=1 iff >=1 suspicion passing rule) | TP | FP | FN | TN | P | R | F1 |
|---|---|---|---|---|---|---|---|
| pollinations-only CONFIRMED | 10 | 7 | 10 | 12 | 0.588 | 0.500 | 0.5405 |
| blockrun-only CONFIRMED | 18 | 17 | 2 | 2 | 0.514 | 0.900 | 0.6545 |
| AND (both CONFIRMED) | 9 | 6 | 11 | 13 | 0.600 | 0.450 | 0.5143 |
| OR (either CONFIRMED) | 19 | 18 | 1 | 1 | 0.514 | 0.950 | 0.6667 |

- The two channels bracket the truth from opposite sides: pollinations is REFUTE-heavy
  (REFUTED on 35 keys where blockrun says CONFIRMED), blockrun is CONFIRM-heavy.
- OR-either slightly beats the unverified E3a control (0.6667 vs 0.6452) with near-perfect
  recall, but remains far below the structural+granite ensemble (0.8889): the E3a
  suspicion producer (frozen Codex A0/A1 Mistral run) is the ceiling of this whole line.
- AND-agreement does NOT buy precision (0.600): both channels can be wrong together
  (8 jointly-confirmed keys on gold=0 cases).
- Conclusion for the program: verification helps only as a precision-restoring signal
  attached to a high-recall producer; it cannot rescue a producer that misses violations
  (the lost/missed-TP class), and per-verifier gating is fragile (62% cross-model
  disagreement).

## Experiment G first result (directive sec. 5): graph digest beats full context (2026-09-21)

Paired probe on the same 94 suspicions, same blockrun channel, same verdict protocol;
only the history representation differs: Base = raw full case context (21-47k chars),
G = provenance-graph digest built from the EXISTING full-architecture-v1 graph
(FactNode facts linked to response tokens by exact value matching; entity-scope
expansion; avg digest 2632 chars; explicit omission notes; raw-text fallback for
non-JSON KB results).

| Arm | TP | FP | FN | TN | P | R | F1 |
|---|---|---|---|---|---|---|---|
| Base (full context) | 18 | 17 | 5 | 6 | 0.514 | 0.783 | 0.6207 |
| G (graph digest + cited region) | 19 | 15 | 4 | 8 | 0.559 | 0.826 | **0.6667** |

- G beats BOTH the Base arm (+.046 F1) and the unverified E3a control (.6452) —
  the first verification variant with a positive delta here.
- Verdict profile: UNCERTAIN collapses 12 -> 1, REFUTED grows 8 -> 28 — the digest
  gives the verifier grounds to be DECISIVE instead of abstaining, without losing recall.
- 3/94 technical failures (vs 15 FAILED in the interrupted pollinations full-context run):
  compact structured context resolves the long-telecom verifiability problem.
- Case flips G vs Base: FP eliminated {airline__5::t1, banking__063::t8, retail__12::t4,
  retail__78::t1}, TP gained {banking__068::t11, telecom service-issue t13},
  TP lost {banking__051::t15}, new FP {banking__080::t30, banking__081::t35}.
- Suspicion transitions: 20 CONFIRMED->REFUTED, 6 REFUTED->CONFIRMED, 5/6
  UNCERTAIN->{CONFIRMED,REFUTED} — real content changes, not noise.
- Answer to directive question (sec. 5, G3): YES for the verifier — the existing graph
  provides materially better grounds to an A4-style verifier than the raw history.
  Effect on the producer-side judge (G2) still untested; G1-vs-G2 separation kept.
